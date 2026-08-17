import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import vm from "node:vm";

async function loadBridge(overrides = {}) {
  const source = await readFile(new URL("../src/userscript.js", import.meta.url), "utf8");
  const context = {
    console,
    crypto: globalThis.crypto,
    GM_getValue: () => "",
    GM_setValue: () => {},
    GM_xmlhttpRequest: undefined,
    ...overrides,
  };
  vm.runInNewContext(source, context);
  return context.HoopsGmBridge;
}

test("generates and persists a 32-byte secret without logging it", async () => {
  const values = new Map();
  const bridge = await loadBridge({
    GM_getValue: (key) => values.get(key) ?? "",
    GM_setValue: (key, value) => values.set(key, value),
  });

  const first = bridge.getSecret();
  const second = bridge.getSecret();
  assert.match(first, /^[0-9a-f]{64}$/);
  assert.equal(second, first);
});

test("health check sends the stored secret and parses the response", async () => {
  let requestOptions;
  const bridge = await loadBridge({
    GM_getValue: () => "a".repeat(64),
    request: undefined,
  });
  const transport = bridge.createTransport({
    storage: { get: () => "a".repeat(64), set: () => {} },
    request: (options) => {
      requestOptions = options;
      options.onload({ status: 200, responseText: '{"status":"ok"}' });
    },
  });

  const health = await transport.healthCheck();
  assert.equal(health.status, "ok");
  assert.equal(requestOptions.url, "http://127.0.0.1:8000/health");
  assert.equal(requestOptions.headers["X-Bridge-Secret"], "a".repeat(64));
});

test("backend failures reject instead of affecting the page", async () => {
  const bridge = await loadBridge();
  const transport = bridge.createTransport({
    storage: { get: () => "b".repeat(64), set: () => {} },
    request: (options) => options.onerror(),
  });

  await assert.rejects(transport.healthCheck(), /backend unreachable/);
});

test("sendPayload forwards a captured envelope to the payloads contract path with the stored secret", async () => {
  let requestOptions;
  const bridge = await loadBridge();
  const transport = bridge.createTransport({
    storage: { get: () => "c".repeat(64), set: () => {} },
    request: (options) => {
      requestOptions = options;
      options.onload({ status: 202, responseText: "{}" });
    },
  });

  const envelope = { schema: "hoops-gm.bridge-payload.v1", source: "fetch" };
  await transport.sendPayload(envelope);

  assert.equal(requestOptions.method, "POST");
  assert.equal(requestOptions.url, "http://127.0.0.1:8000/api/v1/bridge/payloads");
  assert.equal(requestOptions.headers["X-Bridge-Secret"], "c".repeat(64));
  assert.deepEqual(JSON.parse(requestOptions.data), envelope);
});
