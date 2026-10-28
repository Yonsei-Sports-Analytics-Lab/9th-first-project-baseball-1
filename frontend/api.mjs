/** Resolve the FastAPI address for the bundled app and local static preview. */
export function resolveApiRoot(browserLocation, configured = null) {
  if (configured) return String(configured).replace(/\/+$/, "");

  const { protocol, hostname, port, origin } = browserLocation;
  if (protocol === "file:" || (["127.0.0.1", "localhost"].includes(hostname) && port === "8001")) {
    return `http://${hostname || "127.0.0.1"}:8000`;
  }
  return origin;
}

/** Read JSON responses and report a missing API separately from API errors. */
export async function getApiJson(apiRoot, path, signal, fetchImpl = fetch) {
  let response;
  try {
    response = await fetchImpl(`${apiRoot}${path}`, {
      signal,
      headers: { Accept: "application/json" },
    });
  } catch (error) {
    if (error?.name === "AbortError") throw error;
    throw new Error(`비교 API(${apiRoot})에 연결할 수 없습니다. 백엔드를 실행하고 다시 시도해 주세요.`, { cause: error });
  }

  const contentType = response.headers.get("content-type") ?? "";
  if (!contentType.includes("application/json")) {
    throw new Error(`비교 API가 JSON 대신 다른 페이지를 반환했습니다(${response.status}). 백엔드 주소를 확인해 주세요.`);
  }

  const body = await response.json();
  if (!response.ok) {
    const detail = typeof body.detail === "string" ? body.detail : response.statusText;
    throw new Error(`${response.status} ${detail}`);
  }
  return body;
}
