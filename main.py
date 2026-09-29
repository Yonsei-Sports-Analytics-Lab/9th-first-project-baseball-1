"""백엔드 서버 진입점.

실행하면
1. ``src/preprocessing/preprocess_pipeline.py`` 로 전처리를 끝낸 뒤
   (산출물이 이미 있는 단계는 건너뜀, ``--force`` 는 그대로 전달)
   클러스터 결과는 ``data/processed/pitcher_clustered.json`` 에 저장된다.
2. FastAPI 서버를 띄운다.

API
---
LLM 분석은 오래 걸리므로 두 단계로 나눠 호출한다. 프론트엔드는 1번 응답으로 유사 투수를 먼저
보여 주고, 이어서 2번을 호출하는 동안 로딩을 띄운다.

``GET /{player_id}/{year}`` — 유사 투수 (빠름)
    ``src/utils/find_nearest_pitcher.find_nearest_pitcher(player_id, year, top_n)`` 로
    가장 비슷한 투수-시즌 ``(MLB ID, 연도)`` 를 찾아 돌려준다::

        {
          "matched": true,
          "message": null,
          "query":   {"player_id": 660271, "year": 2023},
          "nearest": {"player_id": 543037, "year": 2021},
          "llm_url": "/660271/2023/llm"
        }

``GET /{player_id}/{year}/llm`` — LLM 분석 (느림)
    유사 투수를 서버에서 다시 찾은 뒤(프로필이 메모리에 있어 빠름) 입력 ``(player_id, year)`` 와
    찾은 ``(MLB ID, 연도)`` 를 ``src/utils/llm_client.llm_client(input_mlbid, input_year,
    similar_mlbid, similar_year, search_context)`` 에 넣어 답변(dict)을 돌려준다.
    같은 조합의 답변은 메모리에 캐시해 두 번째 요청부터는 바로 응답한다::

        {
          "matched": true,
          "message": null,
          "query":   {"player_id": 660271, "year": 2023},
          "nearest": {"player_id": 543037, "year": 2021},
          "llm":     { ... llm_client 가 돌려준 dict ... },
          "cached":  false
        }

두 API 모두 ``find_nearest_pitcher`` 가 ``None`` 을 돌려주면(조건에 맞는 유사 투수 없음) 오류가
아니라 정상 응답(200)으로 ``"matched": false`` 와 안내 문구를 보내고, LLM 은 호출하지 않는다::

        {
          "matched": false,
          "message": "조건에 맞는 유사 투수를 찾지 못했습니다.",
          "query":   {"player_id": 660271, "year": 2023},
          "nearest": null,
          "llm_url": null            (/llm 에서는 "llm": null)
        }

``GET /health``
    서버 상태와 로드된 클러스터 JSON 정보.

실행 예시
---------
.. code-block:: bash

    python main.py                         # 전처리(K=10) 후 서버 시작 (127.0.0.1:8000)
    python main.py --k 6 --force cluster   # 클러스터 결과를 다시 만든 뒤 서버 시작
    python main.py --skip-preprocess       # 전처리 없이 서버만
    python main.py --host 0.0.0.0 --port 8000 --cors-origins http://localhost:3000

브라우저에서 ``http://127.0.0.1:8000/docs`` 로 API 를 직접 호출해 볼 수 있다.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Sequence

from fastapi import FastAPI, HTTPException
from fastapi import Path as PathParam
from fastapi.middleware.cors import CORSMiddleware

PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.preprocessing.preprocess_pipeline import (  # noqa: E402
    DEFAULT_K,
    STAGES,
    run_pipeline,
)

import numpy as np
import pandas as pd

from src.utils.find_nearest_pitcher import (  # noqa: E402
    PROFILE_FILE,
    Z_COLS,
    build_profile,
    find_nearest_pitcher,
    load_profile,
)

# --------------------------------------------------------------------------- #
# 설정
# --------------------------------------------------------------------------- #

PROCESSED_DIR = PROJECT_ROOT / "data" / "processed"

#: 서버가 쓰는 클러스터 JSON (전처리 파이프라인이 이 이름으로 저장한다)
CLUSTER_FILE_NAME = "pitcher_clustered.json"

#: `uvicorn main:app` / `fastapi dev main.py` 처럼 main() 을 거치지 않고 띄울 때 쓰는 기본값
ENV_K = "PITCH_GMM_K"
ENV_TOP_N = "NEAREST_TOP_N"
ENV_CORS = "CORS_ORIGINS"  # 쉼표로 구분 (예: "http://localhost:3000,http://127.0.0.1:3000")

DEFAULT_TOP_N = 1

#: 유사 투수가 없을 때 프론트엔드에 보낼 안내 문구
NO_MATCH_MESSAGE = "조건에 맞는 유사 투수를 찾지 못했습니다."
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8000

logger = logging.getLogger("backend")


def load_cluster_index() -> dict[str, dict[str, dict[str, Any]]]:
    """``pitcher_clustered.json`` → ``{MLB ID: {연도: {...}}}``.

    없으면 빈 딕셔너리를 돌려주고, 요청 검증 없이 동작한다.
    """
    path = PROCESSED_DIR / CLUSTER_FILE_NAME
    if not path.exists():
        logger.warning("클러스터 JSON 이 없습니다: %s — 입력 (id, 연도) 검증을 건너뜁니다.", path)
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    logger.info("클러스터 JSON 로드: %s (투수 %s명)", path.name, f"{len(data):,}")
    return data


# --------------------------------------------------------------------------- #
# 앱
# --------------------------------------------------------------------------- #


@asynccontextmanager
async def lifespan(app: FastAPI):
    # main() 에서 app.state 에 넣어 둔 값이 있으면 그것을, 없으면 환경변수를 쓴다.
    state = app.state
    state.k = getattr(state, "k", None) or int(os.getenv(ENV_K, DEFAULT_K))
    state.top_n = getattr(state, "top_n", None) or int(os.getenv(ENV_TOP_N, DEFAULT_TOP_N))
    state.clusters = load_cluster_index()
    yield


app = FastAPI(
    title="Pitcher Repertoire API",
    description="입력한 투수-시즌과 가장 비슷한 투수-시즌을 찾아 LLM 분석을 돌려줍니다.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in os.getenv(ENV_CORS, "*").split(",") if o.strip()],
    allow_methods=["GET"],
    allow_headers=["*"],
)


# --------------------------------------------------------------------------- #
# 다른 모듈 호출 (src/utils — 다른 팀원이 작업 중)
#   함수 이름·인자가 바뀌면 이 두 함수만 고치면 된다.
# --------------------------------------------------------------------------- #


def call_find_nearest_pitcher(player_id: int, year: int, top_n: int) -> tuple[int, int] | None:
    """``find_nearest_pitcher`` 를 호출해 ``(MLB ID, 연도)`` 하나를 받는다.

    조건에 맞는 유사 투수가 없으면 ``None`` 을 돌려준다.
    """
    try:
        result = find_nearest_pitcher(player_id, year, top_n)
    except Exception as error:  # 팀원 코드의 예외를 API 오류로 변환
        logger.exception("find_nearest_pitcher 실패 (%s, %s)", player_id, year)
        raise HTTPException(500, f"find_nearest_pitcher 실행 오류: {error}") from error

    # top_n > 1 이면 리스트로 올 수도 있으니 첫 번째만 쓴다
    if isinstance(result, list):
        result = result[0] if result else None
    if result is None:
        logger.info("(%s, %s) 와 매칭되는 유사 투수 없음", player_id, year)
        return None
    try:
        nearest_id, nearest_year = result
        return int(nearest_id), int(nearest_year)  # numpy 정수 → 파이썬 int
    except (TypeError, ValueError) as error:
        raise HTTPException(
            500, f"find_nearest_pitcher 반환값이 (MLB ID, 연도) 형태가 아닙니다: {result!r}"
        ) from error


def build_search_context(query: tuple[int, int], nearest: tuple[int, int]) -> dict[str, Any] | None:
    """유사 투수 검색 단계의 정보를 ``llm_client`` 의 ``search_context`` 로 넘긴다.

    ``pitcher_profile.csv`` (메모리 캐시)에서 두 투수-시즌의 클러스터·평균 구속·FIP 와
    투구 폼 거리(표준화한 릴리스 좌우·높이, 익스텐션, 팔 각도의 유클리드 거리)를 꺼낸다.
    선택 정보이므로 꺼내지 못하면 ``None`` 을 돌려주고 LLM 호출은 그대로 진행한다.
    """
    try:
        profile = load_profile()

        def row(pid_year: tuple[int, int]):
            pid, year = pid_year
            rows = profile[(profile["player_id"] == pid) & (profile["game_year"] == year)]
            return None if rows.empty else rows.iloc[0]

        target, similar = row(query), row(nearest)
        if target is None or similar is None:
            return None

        def num(value, digits=2):
            return None if pd.isna(value) else round(float(value), digits)

        distance = np.sqrt(((target[Z_COLS].to_numpy(dtype=float)
                             - similar[Z_COLS].to_numpy(dtype=float)) ** 2).sum())
        return {
            "cluster": int(target["cluster"]),
            "input_avg_velocity": num(target["average_velocity"], 1),
            "similar_avg_velocity": num(similar["average_velocity"], 1),
            "input_fip": num(target["FIP"]),
            "similar_fip": num(similar["FIP"]),
            "form_distance": num(distance, 3),
        }
    except Exception:  # 부가 정보라 실패해도 LLM 호출은 막지 않는다
        logger.warning("search_context 를 만들지 못해 생략합니다 (%s, %s)", query, nearest, exc_info=True)
        return None


def call_llm_client(query: tuple[int, int], nearest: tuple[int, int]) -> dict[str, Any]:
    """``llm_client(input_mlbid, input_year, similar_mlbid, similar_year, search_context)`` 를
    호출해 dict 답변(``model``, ``created_at``, ``payload``, ``response``, ``validation_warnings``)을 받는다.
    """
    try:
        from src.utils.llm_client import TransientLLMError, llm_client
    except ImportError as error:
        raise HTTPException(503, f"llm_client 를 불러올 수 없습니다: {error}") from error

    (input_mlbid, input_year), (similar_mlbid, similar_year) = query, nearest
    try:
        answer = llm_client(
            input_mlbid=input_mlbid,
            input_year=input_year,
            similar_mlbid=similar_mlbid,
            similar_year=similar_year,
            search_context=build_search_context(query, nearest),
        )
    except TransientLLMError as error:     # 서버 혼잡·한도 초과 — 잠시 뒤 다시 시도하면 됨
        logger.warning("LLM 일시적 오류 (%s, %s): %s", query, nearest, error)
        raise HTTPException(503, f"LLM 서버가 혼잡합니다. 잠시 후 다시 시도하세요: {error}") from error
    except ValueError as error:            # 해당 시즌 구종 데이터 없음 등
        raise HTTPException(404, f"LLM 입력 데이터를 만들 수 없습니다: {error}") from error
    except ImportError as error:           # openai 패키지 미설치 등
        raise HTTPException(503, f"LLM 호출에 필요한 패키지가 없습니다: {error}") from error
    except Exception as error:             # API 키 없음, 응답 파싱 실패 등
        logger.exception("llm_client 실패 (%s, %s)", query, nearest)
        raise HTTPException(502, f"LLM 호출 오류: {error}") from error

    if not isinstance(answer, dict):
        raise HTTPException(502, f"llm_client 가 dict 가 아닌 {type(answer).__name__} 를 반환했습니다.")
    return answer


# --------------------------------------------------------------------------- #
# 엔드포인트
# --------------------------------------------------------------------------- #


@app.get("/health")
def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "k": app.state.k,
        "top_n": app.state.top_n,
        "cluster_file": CLUSTER_FILE_NAME,
        "pitchers_loaded": len(app.state.clusters),
        "llm_cache_size": len(_llm_cache),
    }


def validate_season(player_id: int, year: int) -> None:
    """``pitcher_clustered.json`` 에 없는 (ID, 연도) 면 404."""
    clusters = app.state.clusters
    if clusters and str(year) not in clusters.get(str(player_id), {}):
        seasons = sorted(clusters.get(str(player_id), {}))
        detail = (
            f"MLB ID {player_id} 의 {year} 시즌 데이터가 없습니다."
            + (f" 가능한 연도: {seasons}" if seasons else " (등록되지 않은 투수)")
        )
        raise HTTPException(404, detail)


def no_match_response(query: dict[str, int], extra_key: str) -> dict[str, Any]:
    """유사 투수가 없을 때의 응답 — 프론트엔드가 안내 문구를 띄울 수 있게 알려 준다."""
    return {
        "matched": False,
        "message": NO_MATCH_MESSAGE,
        "query": query,
        "nearest": None,
        extra_key: None,
    }


#: LLM 답변 캐시 {((입력 id, 연도), (유사 id, 연도)): dict} — 서버를 다시 켜면 비워진다
_llm_cache: dict[tuple[tuple[int, int], tuple[int, int]], dict[str, Any]] = {}


# 두 엔드포인트 모두 async 가 아닌 def 로 둔다
# (FastAPI 가 별도 스레드에서 실행해, LLM 호출이 길어져도 다른 요청을 막지 않는다).
@app.get("/{player_id}/{year}")
def compare_pitcher(
    player_id: int = PathParam(..., gt=0, description="MLB(MLBAM) 선수 ID", examples=[660271]),
    year: int = PathParam(..., ge=1900, le=2100, description="시즌 연도", examples=[2023]),
) -> dict[str, Any]:
    """1단계: 유사 투수만 빠르게 돌려준다."""
    validate_season(player_id, year)
    query = {"player_id": player_id, "year": year}

    nearest = call_find_nearest_pitcher(player_id, year, app.state.top_n)
    if nearest is None:
        return no_match_response(query, "llm_url")

    return {
        "matched": True,
        "message": None,
        "query": query,
        "nearest": {"player_id": nearest[0], "year": nearest[1]},
        "llm_url": f"/{player_id}/{year}/llm",
    }


@app.get("/{player_id}/{year}/llm")
def compare_pitcher_llm(
    player_id: int = PathParam(..., gt=0, description="MLB(MLBAM) 선수 ID", examples=[660271]),
    year: int = PathParam(..., ge=1900, le=2100, description="시즌 연도", examples=[2023]),
) -> dict[str, Any]:
    """2단계: 유사 투수를 서버에서 다시 찾아 LLM 분석을 돌려준다.

    유사 투수를 URL 로 받지 않는 이유: 프론트엔드가 임의의 투수 조합으로 LLM 을 돌리지 못하게 하고,
    1단계와 항상 같은 매칭을 쓰기 위해서다.
    """
    validate_season(player_id, year)
    query = {"player_id": player_id, "year": year}

    nearest = call_find_nearest_pitcher(player_id, year, app.state.top_n)
    if nearest is None:
        return no_match_response(query, "llm")

    key = ((player_id, year), nearest)
    cached = key in _llm_cache
    if not cached:
        _llm_cache[key] = call_llm_client(*key)   # 실패하면 예외가 나서 캐시에 남지 않는다

    return {
        "matched": True,
        "message": None,
        "query": query,
        "nearest": {"player_id": nearest[0], "year": nearest[1]},
        "llm": _llm_cache[key],
        "cached": cached,
    }


# --------------------------------------------------------------------------- #
# 실행
# --------------------------------------------------------------------------- #


def prepare_pitch_arsenal() -> None:
    """``llm_client`` 가 쓰는 구종 집계표를 서버 시작 전에 준비한다.

    ``pitch_arsenal.pkl`` 이 없으면 ``data/raw`` 전체로 만들고(처음 한 번, 오래 걸림),
    있으면 읽기만 한다. 어느 쪽이든 메모리에 올려 두므로 첫 ``/llm`` 요청부터 바로 쓸 수 있다.
    실패해도 서버는 띄운다(``/llm`` 요청 때 다시 시도되고, 그때 오류가 응답으로 간다).
    """
    try:
        from src.utils import llm_client as llm_module
    except ImportError as error:
        logger.warning("llm_client 를 불러올 수 없어 구종 집계 준비를 건너뜁니다: %s", error)
        return

    if llm_module.ARSENAL_PKL.exists():
        logger.info("구종 집계 캐시를 불러옵니다: %s", llm_module.ARSENAL_PKL.name)
    else:
        logger.info("구종 집계 캐시가 없어 data/raw 전체로 생성합니다 (처음 한 번, 수 분 걸릴 수 있음)...")
    try:
        arsenal = llm_module._get_arsenal()   # pkl 생성·로드 + 메모리 캐시 (llm_client 가 요청 때 쓰는 것과 같은 캐시)
        logger.info("구종 집계 준비 완료: %s행", f"{len(arsenal):,}")
    except Exception:
        logger.warning("구종 집계를 준비하지 못했습니다 — /llm 요청 때 다시 시도합니다.", exc_info=True)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="전처리 파이프라인 실행 후 백엔드 서버를 띄웁니다.")
    parser.add_argument("--k", type=int, default=DEFAULT_K,
                        help=f"1차 클러스터(GMM) 개수 K (기본값: {DEFAULT_K})")
    parser.add_argument(
        "--force", nargs="+", choices=STAGES, default=[], metavar="STAGE",
        help=f"전처리에서 산출물이 있어도 다시 실행할 단계 ({', '.join(STAGES)})",
    )
    parser.add_argument("--skip-preprocess", action="store_true",
                        help="전처리 파이프라인을 건너뛰고 서버만 띄웁니다.")
    parser.add_argument("--top-n", type=int, default=DEFAULT_TOP_N,
                        help=f"find_nearest_pitcher 에 넘길 top_n (기본값: {DEFAULT_TOP_N})")
    parser.add_argument("--host", default=DEFAULT_HOST, help=f"기본값: {DEFAULT_HOST}")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"기본값: {DEFAULT_PORT}")
    parser.add_argument(
        "--cors-origins", default=None,
        help="브라우저 접근을 허용할 프론트엔드 주소, 쉼표로 구분 (기본값: 모두 허용 *)",
    )
    parser.add_argument("--log-level", default="INFO",
                        choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    if not args.skip_preprocess:
        logger.info("전처리 파이프라인 실행 (K=%d, force=%s)", args.k, args.force or "없음")
        results = run_pipeline(k=args.k, force=args.force, cluster_output=CLUSTER_FILE_NAME)
        for result in results:
            logger.info(result.summary())

    # 유사 투수 탐색용 프로필 (data/processed/pitcher_profile.csv)
    # 없거나, 클러스터 JSON 이 프로필보다 나중에 만들어졌으면(K 변경·--force cluster 등) 다시 생성
    cluster_file = PROCESSED_DIR / CLUSTER_FILE_NAME
    if not PROFILE_FILE.exists():
        logger.info("투수 프로필이 없어 생성합니다: %s", PROFILE_FILE)
        build_profile()
    elif cluster_file.exists() and cluster_file.stat().st_mtime > PROFILE_FILE.stat().st_mtime:
        logger.info("%s 가 새로 만들어져 투수 프로필을 다시 생성합니다.", cluster_file.name)
        build_profile()
    else:
        logger.info("투수 프로필이 최신입니다 — 생성을 건너뜁니다: %s", PROFILE_FILE.name)

    # LLM 입력용 구종 집계 (data/processed/interim/pitch_arsenal.pkl) — 첫 LLM 요청이 느리지 않도록 미리 준비
    prepare_pitch_arsenal()

    if args.cors_origins:
        # 미들웨어는 앱 시작 전에만 바꿀 수 있으므로, 환경변수 대신 여기서 다시 설정한다
        app.user_middleware = [m for m in app.user_middleware if m.cls is not CORSMiddleware]
        app.add_middleware(
            CORSMiddleware,
            allow_origins=[o.strip() for o in args.cors_origins.split(",") if o.strip()],
            allow_methods=["GET"],
            allow_headers=["*"],
        )

    app.state.k = args.k
    app.state.top_n = args.top_n

    import uvicorn

    uvicorn.run(app, host=args.host, port=args.port, log_level=args.log_level.lower())
    return 0


if __name__ == "__main__":
    sys.exit(main())
