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
    GM_registerMenuCommand: undefined,
    GM_xmlhttpRequest: undefined,
    ...overrides,
  };
  vm.runInNewContext(source, context);
  return context.HoopsGmBridge;
}

test("does not generate a bridge secret before manual pairing", async () => {
  const values = new Map();
  const bridge = await loadBridge({
    GM_getValue: (key) => values.get(key) ?? "",
    GM_setValue: (key, value) => values.set(key, value),
  });

  assert.equal(bridge.getSecret(), null);
  assert.equal(values.size, 0);
});

test("keeps the version 0.2.0 secret under the unchanged GM storage key", async () => {
  const legacySecret = "a".repeat(64);
  const reads = [];
  const writes = [];
  const bridge = await loadBridge();
  const storage = {
    get: (key) => {
      reads.push(key);
      return legacySecret;
    },
    set: (key, value) => writes.push([key, value]),
  };

  assert.equal(bridge.getSecret(storage), legacySecret);
  assert.deepEqual(reads, ["hoops-gm.bridge-secret"]);
  assert.deepEqual(writes, [], "an in-place update must not rotate the paired secret");
});

test("transport exposes only local origin and paired state, never the secret value", async () => {
  const bridge = await loadBridge();
  let stored = "";
  const transport = bridge.createTransport({
    storage: {
      get: () => stored,
      set: (_key, value) => {
        stored = value;
      },
    },
    request: () => {},
  });

  assert.equal(transport.backendOrigin, "http://127.0.0.1:8000");
  assert.equal(transport.isPaired(), false);
  transport.storeSecret("a".repeat(64));
  assert.equal(transport.isPaired(), true);
  assert.equal("secret" in transport, false);
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

test("userscript status compares the installed build without exposing the bridge secret", async () => {
  let requestOptions;
  const bridge = await loadBridge();
  const transport = bridge.createTransport({
    storage: { get: () => "a".repeat(64), set: () => {} },
    request: (options) => {
      requestOptions = options;
      options.onload({
        status: 200,
        responseText: JSON.stringify({
          status: "current",
          installed_version: "0.5.4",
          source_version: "0.5.4",
          served_version: "0.5.4",
          reason: null,
        }),
      });
    },
  });

  const result = await transport.userscriptStatus("0.5.4");

  assert.equal(
    requestOptions.url,
    "http://127.0.0.1:8000/bridge/userscript-status.json?installed_version=0.5.4"
  );
  assert.equal(requestOptions.headers["X-Bridge-Secret"], undefined);
  assert.equal(result.status, "current");
});

test("pairing is registered only through the explicit menu command and stores the returned secret", async () => {
  const bridge = await loadBridge();
  const values = new Map();
  let command;
  const alerts = [];
  const requests = [];
  const secret = "a".repeat(43);
  const transport = bridge.createTransport({
    storage: { get: (key) => values.get(key) ?? "", set: (key, value) => values.set(key, value) },
    request: (options) => {
      requests.push(options);
      if (options.url.endsWith("/pairing")) {
        options.onload({ status: 200, responseText: '{"code":"ABCD1234_EFG"}' });
      } else {
        options.onload({ status: 200, responseText: `{"bridgeSecret":"${secret}"}` });
      }
    },
  });
  transport.storeSecret = (value) => values.set("hoops-gm.bridge-secret", value);

  assert.equal(bridge.installPairingMenu({
    registerMenuCommand: (name, callback) => { command = { name, callback }; },
    prompt: () => "ABCD1234_EFG",
    alert: (message) => alerts.push(message),
    transport,
  }), true);
  assert.equal(command.name, "Pair hoops-gm bridge");
  assert.equal(requests.length, 0, "pairing must not begin on page load");

  command.callback();
  await new Promise((resolve) => setImmediate(resolve));

  assert.equal(requests[0].headers["X-Bridge-Secret"], undefined);
  assert.equal(requests[1].headers["X-Bridge-Secret"], undefined);
  assert.equal(requests[1].headers["X-Hoops-GM-Pairing-Code"], "ABCD1234_EFG");
  assert.equal(values.get("hoops-gm.bridge-secret"), secret);
  assert.match(alerts[0], /ABCD1234_EFG/);
  assert.equal(alerts.at(-1), "hoops-gm bridge paired successfully.");
});

test("pairing failures are controlled and never store a secret", async () => {
  const bridge = await loadBridge();
  const values = new Map();
  const alerts = [];
  const transport = bridge.createTransport({
    storage: { get: () => "", set: (key, value) => values.set(key, value) },
    request: (options) => {
      if (options.url.endsWith("/pairing")) {
        options.onload({ status: 200, responseText: '{"code":"ABCD1234_EFG"}' });
      } else {
        options.onload({ status: 401, responseText: '{"error":"pairing_code_invalid"}' });
      }
    },
  });
  transport.storeSecret = (value) => values.set("hoops-gm.bridge-secret", value);

  const result = await bridge.pairFromMenu({
    transport,
    prompt: () => "wrong-code",
    alert: (message) => alerts.push(message),
  });

  assert.equal(result.status, "failed");
  assert.equal(values.size, 0);
  assert.equal(alerts.at(-1), "Pairing failed: the code is invalid, expired, or has already been used.");
});

test("pairing rejects an invalid backend response without storing it", async () => {
  const bridge = await loadBridge();
  const values = new Map();
  const alerts = [];
  const transport = bridge.createTransport({
    storage: { get: () => "", set: () => {} },
    request: (options) => options.onload({
      status: 200,
      responseText: options.url.endsWith("/pairing")
        ? '{"code":"ABCD1234_EFG"}'
        : '{"bridgeSecret":"not-a-secret"}',
    }),
  });
  transport.storeSecret = (value) => values.set("hoops-gm.bridge-secret", value);

  const result = await bridge.pairFromMenu({
    transport,
    prompt: () => "ABCD1234_EFG",
    alert: (message) => alerts.push(message),
  });

  assert.equal(result.status, "failed");
  assert.equal(values.size, 0);
  assert.equal(alerts.at(-1), "Pairing failed. Check that the local backend is running and try again.");
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
      options.onload({ status: 201, responseText: '{"id":17,"status":"stored"}' });
    },
  });

  const envelope = { schema: "hoops-gm.bridge-payload.v1", source: "fetch" };
  await transport.sendPayload(envelope);

  assert.equal(requestOptions.method, "POST");
  assert.equal(requestOptions.url, "http://127.0.0.1:8000/api/v1/bridge/payloads");
  assert.equal(requestOptions.headers["X-Bridge-Secret"], "c".repeat(64));
  assert.deepEqual(JSON.parse(requestOptions.data), envelope);
});

test("sendPayload rejects a non-201 or malformed storage acknowledgement", async () => {
  const bridge = await loadBridge();
  const responses = [
    { status: 200, responseText: '{"id":1,"status":"stored"}' },
    { status: 201, responseText: '{"id":1,"status":"accepted"}' },
  ];
  const transport = bridge.createTransport({
    storage: { get: () => "c".repeat(64), set: () => {} },
    request: (options) => options.onload(responses.shift()),
  });

  await assert.rejects(
    transport.sendPayload({ schema: "hoops-gm.bridge-payload.v1" }),
    /expected HTTP 201/
  );
  await assert.rejects(
    transport.sendPayload({ schema: "hoops-gm.bridge-payload.v1" }),
    /did not acknowledge durable payload storage/
  );
});
