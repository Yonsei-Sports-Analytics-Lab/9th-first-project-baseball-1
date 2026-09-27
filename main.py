"""프로젝트의 기본 명령행 진입점."""

from src.visualization.dashboard_formatter import PitchCsvError, main


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except PitchCsvError as error:
        raise SystemExit(f"오류: {error}") from error
