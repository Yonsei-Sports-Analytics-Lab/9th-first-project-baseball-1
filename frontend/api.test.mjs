import assert from "node:assert/strict";
import test from "node:test";

import { getApiJson, resolveApiRoot } from "./api.mjs";

test("static preview sends API requests to FastAPI on port 8000", () => {
  assert.equal(resolveApiRoot({
    protocol: "http:", hostname: "127.0.0.1", port: "8001", origin: "http://127.0.0.1:8001",
  }), "http://127.0.0.1:8000");
});

test("bundled frontend keeps the API on the same origin", () => {
  assert.equal(resolveApiRoot({
    protocol: "http:", hostname: "127.0.0.1", port: "8000", origin: "http://127.0.0.1:8000",
  }), "http://127.0.0.1:8000");
});

test("API address can be configured explicitly", () => {
  assert.equal(resolveApiRoot({}, "https://api.example.org/"), "https://api.example.org");
});

test("an unavailable API reports the backend connection problem", async () => {
  await assert.rejects(
    getApiJson("http://127.0.0.1:8000", "/pitchers", undefined, async () => {
      throw new TypeError("Failed to fetch");
    }),
    /비교 API\(http:\/\/127\.0\.0\.1:8000\)에 연결할 수 없습니다/,
  );
});

test("an HTML 404 is identified as an API routing problem", async () => {
  await assert.rejects(
    getApiJson("http://127.0.0.1:8001", "/pitchers", undefined, async () => new Response(
      "<!doctype html><title>File not found</title>",
      { status: 404, headers: { "content-type": "text/html" } },
    )),
    /JSON 대신 다른 페이지를 반환했습니다\(404\)/,
  );
});
