import { getApiJson, resolveApiRoot } from "./api.mjs?v=2";

const apiRoot = resolveApiRoot(location, window.PITCH_TWIN_API);

const homeView = document.querySelector("#home-view");
const resultView = document.querySelector("#result-view");
const resultData = document.querySelector("#result-data");
const resultStatus = document.querySelector("#result-status");
const analysisBody = document.querySelector("#analysis-body");
const clusterOverview = document.querySelector("#cluster-overview");
const analysisMeta = document.querySelector("#analysis-meta");
const toast = document.querySelector("#toast");
const forms = [...document.querySelectorAll("#hero-search, #result-search")];

let activeController = null;
let activeSearch = null;
let toastTimer = null;
let threeViewerModule = null;

const format = (value, digits = 1) => value == null || Number.isNaN(Number(value)) ? "—" : Number(value).toFixed(digits);
const clamp = (value, min, max) => Math.max(min, Math.min(max, value));
const escapeHtml = (value) => String(value ?? "").replace(/[&<>'"]/g, (character) => ({
  "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;",
})[character]);

function displayName(value) {
  const parts = String(value ?? "").split(",", 2).map((part) => part.trim());
  return parts.length === 2 ? `${parts[1]} ${parts[0]}` : parts[0];
}

async function getJson(path, signal) {
  return getApiJson(apiRoot, path, signal);
}

function showToast(message) {
  clearTimeout(toastTimer);
  toast.textContent = message;
  toast.hidden = false;
  toastTimer = setTimeout(() => { toast.hidden = true; }, 5200);
}

function setLoading(message = "유사 투수 탐색 중") {
  resultData.hidden = true;
  resultStatus.innerHTML = `
    <span class="status__spinner" aria-hidden="true"></span>
    <h2>${escapeHtml(message)}</h2>
    <p>같은 군집에서 구속과 투구 폼이 가까운 후보를 순서대로 비교합니다.</p>`;
}

function setError(title, message) {
  resultData.hidden = true;
  resultStatus.innerHTML = `
    <h2>${escapeHtml(title)}</h2>
    <p>${escapeHtml(message)}</p>
    <button class="button button--secondary" type="button" data-go-home>다른 투수 검색하기</button>`;
  resultStatus.querySelector("[data-go-home]")?.addEventListener("click", showHome);
}

function showHome() {
  activeController?.abort();
  activeController = null;
  document.body.classList.remove("is-result");
  homeView.hidden = false;
  resultView.hidden = true;
  history.pushState({}, "", location.pathname);
  window.scrollTo({ top: 0, behavior: "smooth" });
}

function showResults() {
  document.body.classList.add("is-result");
  homeView.hidden = true;
  resultView.hidden = false;
  window.scrollTo({ top: 0, behavior: "auto" });
}

function formValues(form) {
  return {
    name: form.elements.pitcher.value.trim(),
    playerId: form.elements["player-id"].value.trim(),
    year: Number(form.elements.year.value),
    rank: Number(form.elements.rank.value),
  };
}

function syncForms(values) {
  for (const form of forms) {
    form.elements.pitcher.value = values.name;
    form.elements["player-id"].value = values.playerId;
    form.elements.year.value = String(values.year);
    form.elements.rank.value = String(values.rank);
  }
}

async function resolvePlayer(values, signal) {
  if (values.playerId) return Number(values.playerId);
  if (/^\d+$/.test(values.name)) return Number(values.name);
  if (!values.name) throw new Error("투수 이름 또는 MLB ID를 입력해 주세요.");

  const params = new URLSearchParams({ query: values.name, year: String(values.year), limit: "12" });
  const result = await getJson(`/pitchers?${params}`, signal);
  const normalized = values.name.toLocaleLowerCase();
  const exact = result.items.find((item) => item.player_name.toLocaleLowerCase() === normalized);
  const selected = exact ?? (result.items.length === 1 ? result.items[0] : null);
  if (!selected) {
    if (!result.items.length) throw new Error(`${values.year} 시즌의 '${values.name}' 투수를 찾지 못했습니다.`);
    throw new Error("검색 목록에서 투수를 선택해 주세요.");
  }
  values.name = selected.player_name;
  values.playerId = String(selected.player_id);
  return selected.player_id;
}

function setupAutocomplete(form) {
  const input = form.elements.pitcher;
  const hidden = form.elements["player-id"];
  const suggestions = form.querySelector(".suggestions");
  let debounceTimer;
  let requestController;
  let selectedIndex = -1;

  const close = () => { suggestions.hidden = true; selectedIndex = -1; };
  const select = (item) => {
    input.value = item.player_name;
    hidden.value = String(item.player_id);
    if (item.seasons.length && !item.seasons.includes(Number(form.elements.year.value))) {
      form.elements.year.value = String(item.seasons[0]);
    }
    close();
  };

  async function update() {
    const query = input.value.trim();
    if (query.length < 2 || /^\d+$/.test(query)) { close(); return; }
    requestController?.abort();
    requestController = new AbortController();
    const params = new URLSearchParams({ query, year: form.elements.year.value, limit: "8" });
    try {
      const result = await getJson(`/pitchers?${params}`, requestController.signal);
      suggestions.replaceChildren();
      if (!result.items.length) {
        const empty = document.createElement("p");
        empty.className = "suggestions__empty";
        empty.textContent = "일치하는 투수가 없습니다.";
        suggestions.append(empty);
      } else {
        for (const item of result.items) {
          const button = document.createElement("button");
          button.type = "button";
          button.setAttribute("role", "option");
          const strong = document.createElement("strong");
          strong.textContent = item.player_name;
          const meta = document.createElement("span");
          meta.textContent = `${item.seasons.join(" · ")}  #${item.player_id}`;
          button.append(strong, meta);
          button.addEventListener("mousedown", (event) => event.preventDefault());
          button.addEventListener("click", () => select(item));
          suggestions.append(button);
        }
      }
      suggestions.hidden = false;
    } catch (error) {
      if (error.name !== "AbortError") close();
    }
  }

  input.addEventListener("input", () => {
    hidden.value = "";
    clearTimeout(debounceTimer);
    debounceTimer = setTimeout(update, 180);
  });
  input.addEventListener("focus", () => { if (input.value.trim().length >= 2 && !hidden.value) update(); });
  input.addEventListener("blur", () => setTimeout(close, 120));
  input.addEventListener("keydown", (event) => {
    const options = [...suggestions.querySelectorAll('[role="option"]')];
    if (suggestions.hidden || !options.length) return;
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      selectedIndex = event.key === "ArrowDown"
        ? (selectedIndex + 1) % options.length
        : (selectedIndex - 1 + options.length) % options.length;
      options.forEach((option, index) => option.setAttribute("aria-selected", String(index === selectedIndex)));
      options[selectedIndex].scrollIntoView({ block: "nearest" });
    } else if (event.key === "Enter" && selectedIndex >= 0) {
      event.preventDefault();
      options[selectedIndex].click();
    } else if (event.key === "Escape") close();
  });
  form.elements.year.addEventListener("change", () => { hidden.value = ""; });
}

function profileCardMarkup(role, profile, context, input) {
  const fastball = profile.primary_fastball ?? {};
  const arsenal = profile.arsenal ?? [];
  const fip = input ? context?.input_fip : context?.similar_fip;
  const pitches = arsenal.reduce((sum, pitch) => sum + Number(pitch.n_pitches ?? 0), 0);
  const hand = profile.throws === "L" ? "좌투" : "우투";
  const name = displayName(profile.player_name);
  const metrics = [
    ["평균 구속", format(fastball.velo_mph), "mph", ""],
    ["FIP", format(fip, 2), "", "metric--fip"],
    ["팔 각도", format(fastball.arm_angle_deg), "°", ""],
    ["평균 IVB", format(fastball.ivb_in), "in", ""],
    ["평균 HB", format(fastball.hb_in), "in", ""],
    ["분석 투구 수", pitches ? pitches.toLocaleString("ko-KR") : "—", "", ""],
  ];
  return `
    <p class="pitcher-card__label">${escapeHtml(role)}</p>
    <div class="pitcher-card__head">
      <div><h2>${escapeHtml(name)}</h2><p class="pitcher-card__sub">${profile.season} 시즌 · ${hand} · MLB ID ${profile.pitcher_id}</p></div>
      <span class="pitch-badge">패스트볼 클러스터 ${escapeHtml(context?.cluster ?? "—")}</span>
    </div>
    <dl class="metrics">
      ${metrics.map(([label, value, unit, className]) => `<div class="metric ${className}"><dt>${label}</dt><dd>${value}${unit ? `<small>${unit}</small>` : ""}</dd></div>`).join("")}
    </dl>`;
}

function clusterIntroMarkup(profiles) {
  const context = profiles?.search_context ?? {};
  const center = context.cluster_profile ?? {};
  const input = profiles?.input_pitcher;
  const similar = profiles?.similar_pitcher;
  const inputName = displayName(input?.player_name);
  const similarName = displayName(similar?.player_name);
  const centerText = center.ivb_in != null && center.hb_in != null && center.arm_angle_deg != null
    ? `이 군집의 GMM 중심은 보정 IVB ${format(center.ivb_in)} in, 암사이드 HB ${format(center.hb_in)} in, 팔 각도 ${format(center.arm_angle_deg)}°입니다.`
    : "이 군집은 보정 수직·수평 움직임과 팔 각도가 비슷한 패스트볼 투구로 구성됩니다.";
  return `<div class="cluster-explanation">
    <p class="section-label">FASTBALL CLUSTER</p>
    <h3>패스트볼 클러스터 ${escapeHtml(context.cluster ?? "—")}</h3>
    <p>${escapeHtml(input?.season)} 시즌 ${escapeHtml(inputName)}의 패스트볼은 이 군집에 가장 많이 속합니다. ${escapeHtml(centerText)} ${escapeHtml(similarName)}도 같은 군집에 속해 변화구 구성을 비교합니다.</p>
    <p class="cluster-explanation__note">군집 번호는 성적 순위가 아니라 움직임·팔 각도로 만든 GMM 성분 번호입니다.</p>
  </div>`;
}

function renderAnalysisLoading() {
  document.querySelector("#analysis-label").textContent = "SECONDARY PITCHES";
  analysisMeta.textContent = "후보 분석 중";
  analysisBody.innerHTML = '<div class="analysis-loading" aria-label="변화구 후보를 불러오는 중"><div class="skeleton"></div><div class="skeleton"></div><div class="skeleton"></div></div>';
  document.querySelector("#evidence-tags").replaceChildren();
}

function renderAnalysis(llm) {
  const response = llm?.response ?? {};
  const similarities = response.fastball_comparison?.similarities ?? [];
  const differences = response.fastball_comparison?.differences ?? [];
  const recommendations = (response.recommendations ?? []).filter((item) => !["FF", "SI", "FC"].includes(item.pitch_type)).slice(0, 3);
  const excluded = (response.not_recommended ?? []).slice(0, 3);
  const summary = response.summary || "분석 설명이 제공되지 않았습니다.";
  const ruleBased = llm?.source === "rule_based";
  document.querySelector("#analysis-label").textContent = ruleBased ? "STATCAST PITCH TARGETS" : "AI PITCH TARGETS";
  analysisMeta.textContent = ruleBased
    ? (llm?.fallback_reason === "llm_unavailable"
      ? "AI 일시 오류 · Statcast 참고"
      : "API 키 없음 · Statcast 참고")
    : `${llm?.model ?? "AI"} 분석`;
  analysisBody.innerHTML = `
    <div class="analysis-copy"><p>${escapeHtml(summary)}</p></div>
    ${recommendations.length ? recommendations.map((item, index) => {
      const shape = item.target_shape ?? {};
      const shapeText = [
        shape.velo_mph == null ? null : `${format(shape.velo_mph)} mph`,
        shape.ivb_in == null ? null : `IVB ${format(shape.ivb_in)} in`,
        shape.hb_in == null ? null : `HB ${format(shape.hb_in)} in`,
      ].filter(Boolean).join(" · ");
      const action = { add: "새 구종", refine: "shape 조정", usage: "구사율 조정" }[item.action] ?? item.action ?? "참고 후보";
      return `<article class="recommendation">
        <div class="recommendation__head"><h3>${index + 1}. ${escapeHtml(item.pitch_name ?? item.pitch_type)} <small>${escapeHtml(item.pitch_type)}</small></h3><span class="tag">${escapeHtml(action)}</span>${item.confidence && item.confidence !== "해당 없음" ? `<span class="tag">신뢰도 ${escapeHtml(item.confidence)}</span>` : ""}</div>
        ${shapeText ? `<p class="recommendation__shape"><b>참고 목표 shape</b> ${escapeHtml(shapeText)}</p>` : ""}
        ${(item.rationale ?? []).slice(0, 3).map((reason) => `<p>${escapeHtml(reason)}</p>`).join("")}
        ${item.usage_plan ? `<p><b>해석:</b> ${escapeHtml(item.usage_plan)}</p>` : ""}
      </article>`;
    }).join("") : `<p class="analysis-empty">비교 투수의 변화구에서 수치가 충분한 참고 후보를 찾지 못했습니다.</p>`}
    ${excluded.length ? `<p class="analysis-empty">추천 제외: ${excluded.map((item) => `${escapeHtml(item.pitch_type)} (${escapeHtml(item.reason)})`).join(" · ")}</p>` : ""}
    ${(similarities.length || differences.length) ? `<div class="analysis-points">
      ${similarities[0] ? `<div class="analysis-point"><strong>닮은 점</strong><p>${escapeHtml(similarities[0])}</p></div>` : ""}
      ${differences[0] ? `<div class="analysis-point"><strong>갈린 지점</strong><p>${escapeHtml(differences[0])}</p></div>` : ""}
    </div>` : ""}`;
  const tags = ["Statcast IVB/HB", "팔 각도", "구종 구사율", "FIP"];
  if (recommendations.length) tags.push("RV/100");
  const tagBox = document.querySelector("#evidence-tags");
  tagBox.innerHTML = tags.map((tag) => `<span class="tag">${tag}</span>`).join("");
}

function renderAnalysisError(message) {
  analysisMeta.textContent = "프로필 비교 완료";
  analysisBody.innerHTML = `<div class="analysis-copy"><p>변화구 후보를 불러오지 못했습니다. 두 투수의 프로필과 구종별 3D 궤적은 확인할 수 있습니다.</p><p class="pitcher-card__sub">${escapeHtml(message)}</p></div>`;
}

function renderComparison(response, search) {
  const profiles = response.profiles;
  if (!profiles?.input_pitcher || !profiles?.similar_pitcher) {
    throw new Error(response.profile_error || "비교 프로필이 응답에 없습니다.");
  }
  const input = profiles.input_pitcher;
  const similar = profiles.similar_pitcher;
  const context = profiles.search_context ?? {};
  const inputName = displayName(input.player_name);
  const similarName = displayName(similar.player_name);

  activeSearch = { ...search, name: inputName, playerId: String(input.pitcher_id) };
  syncForms(activeSearch);
  document.querySelector("#match-kicker").textContent = `패스트볼 클러스터 ${context.cluster ?? "—"} · ${input.throws === "L" ? "좌투" : "우투"} · ${search.rank}순위 매칭`;
  document.querySelector("#match-title").textContent = `${inputName} vs ${similarName}`;
  document.querySelector("#input-card").innerHTML = profileCardMarkup("검색한 투수", input, context, true);
  document.querySelector("#similar-card").innerHTML = profileCardMarkup("닮은 투수 · FIP 더 낮음", similar, context, false);
  document.querySelector("#legend-input").textContent = inputName;
  document.querySelector("#legend-similar").textContent = similarName;
  const trajectoryGrid = document.querySelector("#trajectory-grid");
  threeViewerModule?.unmountComparison(trajectoryGrid);
  trajectoryGrid.innerHTML = '<p class="trajectory-loading" role="status">3D 궤적 준비 중…</p>';
  const previousMap = clusterOverview.querySelector("#cluster-map");
  if (previousMap) threeViewerModule?.unmountClusterMap?.(previousMap);
  clusterOverview.innerHTML = `${clusterIntroMarkup(profiles)}<div id="cluster-map" class="cluster-map-host"><p class="cluster-map-loading" role="status">전체 패스트볼 GMM 지도 준비 중…</p></div>`;

  document.querySelector("#previous-rank").disabled = search.rank <= 1;
  document.querySelector("#next-rank").disabled = search.rank >= 5;
  document.querySelector("#next-rank-cta").disabled = search.rank >= 5;
  resultStatus.replaceChildren();
  resultData.hidden = false;
  renderAnalysisLoading();
  document.title = `${inputName} vs ${similarName} — PITCH TWIN`;
}

async function renderTrajectories(response, signal) {
  const container = document.querySelector("#trajectory-grid");
  const ids = [response.query, response.nearest];
  try {
    const [input, similar] = await Promise.all(ids.map(({ player_id, year }) =>
      getJson(`/trajectory/${player_id}/${year}`, signal)));
    threeViewerModule = await import("./three-viewer.js?v=15");
    if (signal.aborted) return;
    container.replaceChildren();
    threeViewerModule.mountComparison(container, input, similar);
  } catch (error) {
    if (error.name !== "AbortError" && !signal.aborted) {
      container.innerHTML = `<p class="trajectory-loading" role="alert">3D 궤적을 불러오지 못했습니다: ${escapeHtml(error.message)}</p>`;
    }
  }
}

async function renderClusterMap(response, signal) {
  const container = clusterOverview.querySelector("#cluster-map");
  try {
    const data = await getJson(response.cluster_map_url, signal);
    const module = await import("./three-viewer.js?v=15");
    if (signal.aborted || !container.isConnected) return;
    threeViewerModule = module;
    container.replaceChildren();
    module.mountClusterMap(container, data, {
      input: displayName(response.profiles.input_pitcher.player_name),
      similar: displayName(response.profiles.similar_pitcher.player_name),
    });
  } catch (error) {
    if (error.name !== "AbortError" && !signal.aborted && container.isConnected) {
      container.innerHTML = `<p class="cluster-map-loading" role="alert">GMM 지도를 불러오지 못했습니다: ${escapeHtml(error.message)}</p>`;
    }
  }
}

async function runComparison(values, { pushHistory = true } = {}) {
  activeController?.abort();
  const controller = new AbortController();
  activeController = controller;
  showResults();
  setLoading();

  try {
    const playerId = await resolvePlayer(values, controller.signal);
    values.playerId = String(playerId);
    syncForms(values);
    const first = await getJson(`/${playerId}/${values.year}?rank=${values.rank}`, controller.signal);
    if (!first.matched) {
      setError("매칭 결과 없음", `${values.rank}순위 후보가 없습니다. 더 앞선 순위를 선택하거나 다른 시즌을 검색해 주세요.`);
      return;
    }
    renderComparison(first, values);
    void renderTrajectories(first, controller.signal);
    void renderClusterMap(first, controller.signal);
    if (pushHistory) {
      const params = new URLSearchParams({ player: String(playerId), year: String(values.year), rank: String(values.rank) });
      history.pushState(values, "", `${location.pathname}?${params}`);
    }

    try {
      const second = await getJson(first.llm_url, controller.signal);
      if (second.matched && second.llm) renderAnalysis(second.llm);
      else renderAnalysisError(second.message ?? "AI 분석 결과가 없습니다.");
    } catch (error) {
      if (error.name !== "AbortError") renderAnalysisError(error.message);
    }
  } catch (error) {
    if (error.name !== "AbortError") {
      setError("비교 오류", error.message);
      showToast(error.message);
    }
  }
}

function changeRank(delta) {
  if (!activeSearch) return;
  const rank = clamp(activeSearch.rank + delta, 1, 5);
  runComparison({ ...activeSearch, rank });
}

for (const form of forms) {
  setupAutocomplete(form);
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    const values = formValues(form);
    if (!values.name) { showToast("투수 이름 또는 MLB ID를 입력해 주세요."); return; }
    runComparison(values);
  });
}

document.querySelectorAll("[data-example-name]").forEach((button) => {
  button.addEventListener("click", () => runComparison({
    name: button.dataset.exampleName,
    playerId: "",
    year: Number(button.dataset.exampleYear),
    rank: 1,
  }));
});

document.querySelectorAll("[data-scroll]").forEach((button) => {
  button.addEventListener("click", () => document.querySelector(`#${button.dataset.scroll}`)?.scrollIntoView({ behavior: "smooth" }));
});

document.querySelector("#previous-rank").addEventListener("click", () => changeRank(-1));
document.querySelector("#next-rank").addEventListener("click", () => changeRank(1));
document.querySelector("#next-rank-cta").addEventListener("click", () => changeRank(1));
document.querySelector(".result-search__brand").addEventListener("click", showHome);
document.querySelector(".result-search__brand").setAttribute("role", "button");
document.querySelector(".result-search__brand").setAttribute("tabindex", "0");
document.querySelector(".result-search__brand").addEventListener("keydown", (event) => { if (event.key === "Enter" || event.key === " ") showHome(); });

window.addEventListener("popstate", () => {
  const params = new URLSearchParams(location.search);
  if (!params.has("player")) { showHome(); return; }
  runComparison({
    name: params.get("player"),
    playerId: params.get("player"),
    year: Number(params.get("year") || 2023),
    rank: Number(params.get("rank") || 1),
  }, { pushHistory: false });
});

const initial = new URLSearchParams(location.search);
if (initial.has("player")) {
  runComparison({
    name: initial.get("player"),
    playerId: initial.get("player"),
    year: Number(initial.get("year") || 2023),
    rank: Number(initial.get("rank") || 1),
  }, { pushHistory: false });
}
