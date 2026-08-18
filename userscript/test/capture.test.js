import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import vm from "node:vm";

function toPlain(value) {
  // Objects produced inside the vm context belong to a different realm, so
  // their Object.prototype differs from this file's -- deepStrictEqual
  // treats that as unequal even when every field matches. Round-tripping
  // through JSON compares structure only, which is what these tests intend.
  return JSON.parse(JSON.stringify(value));
}

async function loadCapture(overrides = {}) {
  const source = await readFile(new URL("../src/capture.js", import.meta.url), "utf8");
  const context = {
    console,
    URL,
    // No `window` in these contexts, so capture.js's auto-install guard is
    // never exercised here -- every test wires installFetch/installXHR
    // explicitly against a fake `win` object instead.
    ...overrides,
  };
  vm.createContext(context);
  vm.runInContext(source, context);
  return context.HoopsGmCapture;
}

function fakeResponse({ status = 200, ok = true, body = "", contentType = "application/json" } = {}) {
  return {
    status,
    ok,
    headers: { get: (name) => (name.toLowerCase() === "content-type" ? contentType : null) },
    clone() {
      return fakeResponse({ status, ok, body, contentType });
    },
    text: async () => body,
  };
}

// ---------------------------------------------------------------------------
// Filtering
// ---------------------------------------------------------------------------

test("shouldCapture matches only the exact /fxpa/req pathname", async () => {
  const capture = await loadCapture();
  assert.equal(capture.shouldCapture("https://www.fantrax.com/fxpa/req?leagueId=abc"), true);
  assert.equal(capture.shouldCapture("/fxpa/req"), true);
  assert.equal(capture.shouldCapture("/fxpa/req?method=getDraftPicks"), true);
});

test("shouldCapture rejects paths that merely look similar or are unrelated", async () => {
  const capture = await loadCapture();
  assert.equal(capture.shouldCapture("/fxpa/reqSomethingElse"), false);
  assert.equal(capture.shouldCapture("/fxpa/req/sub"), false);
  assert.equal(capture.shouldCapture("https://example.test/fxpa/req"), false);
  assert.equal(capture.shouldCapture("/fxea/general/getAdp"), false);
  assert.equal(capture.shouldCapture("/other"), false);
  assert.equal(capture.shouldCapture(""), false);
  assert.equal(capture.shouldCapture(undefined), false);
  assert.equal(capture.shouldCapture("not a url"), false);
});

test("isFantraxLeaguePage accepts only scoped HTTPS league pages", async () => {
  const capture = await loadCapture();
  assert.equal(
    capture.isFantraxLeaguePage("https://www.fantrax.com/fantasy/league/abc/draft"),
    true
  );
  assert.equal(
    capture.isFantraxLeaguePage("https://fantrax.com/fantasy/league/abc?view=players"),
    true
  );
  assert.equal(capture.isFantraxLeaguePage("https://www.fantrax.com/fantasy/league/"), false);
  assert.equal(capture.isFantraxLeaguePage("https://www.fantrax.com/fantasy/home"), false);
  assert.equal(
    capture.isFantraxLeaguePage("http://www.fantrax.com/fantasy/league/abc"),
    false
  );
  assert.equal(
    capture.isFantraxLeaguePage("https://example.test/fantasy/league/abc"),
    false
  );
});

// ---------------------------------------------------------------------------
// Normalization: malformed / non-JSON bodies
// ---------------------------------------------------------------------------

test("normalizeBody parses valid JSON", async () => {
  const capture = await loadCapture();
  const body = capture.normalizeBody('{"status":"ok","picks":[1,2,3]}');
  assert.deepEqual(toPlain(body.json), { status: "ok", picks: [1, 2, 3] });
  assert.equal(body.parseError, null);
  assert.equal(body.raw, '{"status":"ok","picks":[1,2,3]}');
});

test("normalizeBody preserves raw text and records the error for malformed JSON", async () => {
  const capture = await loadCapture();
  const body = capture.normalizeBody("<html>502 Bad Gateway</html>");
  assert.equal(body.json, null);
  assert.equal(body.raw, "<html>502 Bad Gateway</html>");
  assert.equal(typeof body.parseError, "string");
  assert.ok(body.parseError.length > 0);
});

test("normalizeBody handles an empty body without throwing", async () => {
  const capture = await loadCapture();
  const body = capture.normalizeBody("");
  assert.equal(body.json, null);
  assert.equal(body.raw, "");
  assert.equal(body.parseError, "empty response body");
});

test("normalizeBody handles non-string input without throwing", async () => {
  const capture = await loadCapture();
  const body = capture.normalizeBody(undefined);
  assert.equal(body.json, null);
  assert.equal(body.parseError, "empty response body");
});

// ---------------------------------------------------------------------------
// Envelope shape
// ---------------------------------------------------------------------------

test("buildEnvelope produces the typed schema with no headers and no request body", async () => {
  const capture = await loadCapture();
  const envelope = capture.buildEnvelope({
    source: "fetch",
    url: "https://www.fantrax.com/fxpa/req?leagueId=abc",
    method: "post",
    status: 200,
    ok: true,
    contentType: "application/json; charset=utf-8",
    raw: '{"status":"ok"}',
    capturedAtMs: 1700000000000,
  });

  assert.equal(envelope.schema, capture.ENVELOPE_SCHEMA);
  assert.equal(envelope.source, "fetch");
  assert.equal(envelope.capturedAt, new Date(1700000000000).toISOString());
  assert.deepEqual(toPlain(envelope.request), {
    method: "POST",
    url: "https://www.fantrax.com/fxpa/req?leagueId=abc",
  });
  assert.deepEqual(toPlain(envelope.response), {
    status: 200,
    ok: true,
    contentType: "application/json; charset=utf-8",
  });
  assert.deepEqual(toPlain(envelope.body), { raw: '{"status":"ok"}', json: { status: "ok" }, parseError: null });
  assert.equal(typeof envelope.dedupeKey, "string");

  // No sensitive/raw headers or request body ever appear on the envelope,
  // even though this is a JSON object that would happily carry them.
  const keys = Object.keys(envelope);
  assert.deepEqual(keys.sort(), ["body", "capturedAt", "dedupeKey", "request", "response", "schema", "source"]);
  assert.deepEqual(Object.keys(envelope.request).sort(), ["method", "url"]);
  assert.ok(!("headers" in envelope));
  assert.ok(!JSON.stringify(envelope).toLowerCase().includes("cookie"));
});

test("computeDedupeKey is stable for identical inputs and differs when the body changes", async () => {
  const capture = await loadCapture();
  const a = capture.computeDedupeKey("GET", "/fxpa/req", '{"a":1}');
  const b = capture.computeDedupeKey("GET", "/fxpa/req", '{"a":1}');
  const c = capture.computeDedupeKey("GET", "/fxpa/req", '{"a":2}');
  assert.equal(a, b);
  assert.notEqual(a, c);
});

// ---------------------------------------------------------------------------
// Dedupe cache
// ---------------------------------------------------------------------------

test("createDedupeCache reports a key as seen only after the first time", async () => {
  const capture = await loadCapture();
  const cache = capture.createDedupeCache();
  assert.equal(cache.seen("k1"), false);
  assert.equal(cache.seen("k1"), true);
  assert.equal(cache.seen("k2"), false);
});

test("createDedupeCache evicts the oldest entry once past maxEntries", async () => {
  const capture = await loadCapture();
  const cache = capture.createDedupeCache({ maxEntries: 2 });
  cache.seen("k1");
  cache.seen("k2");
  cache.seen("k3"); // evicts k1
  assert.equal(cache.seen("k1"), false, "k1 should have been evicted and is fresh again");
});

// ---------------------------------------------------------------------------
// createCapture: forwarding + dedupe end-to-end
// ---------------------------------------------------------------------------

function flushMicrotasks() {
  return new Promise((resolve) => setTimeout(resolve, 0));
}

test("handleCaptured forwards a matching capture through transport.sendPayload", async () => {
  const capture = await loadCapture();
  const sent = [];
  const transport = { sendPayload: async (envelope) => sent.push(envelope) };
  const instance = capture.createCapture({ transport, now: () => 1700000000000 });

  instance.handleCaptured({
    source: "fetch",
    url: "https://www.fantrax.com/fxpa/req?method=getDraftPicks",
    method: "POST",
    status: 200,
    ok: true,
    contentType: "application/json",
    raw: '{"picks":[]}',
  });
  await flushMicrotasks();

  assert.equal(sent.length, 1);
  assert.equal(sent[0].request.url, "https://www.fantrax.com/fxpa/req?method=getDraftPicks");
  assert.deepEqual(toPlain(sent[0].body.json), { picks: [] });
});

test("handleCaptured never forwards a non-matching URL", async () => {
  const capture = await loadCapture();
  const sent = [];
  const transport = { sendPayload: async (envelope) => sent.push(envelope) };
  const instance = capture.createCapture({ transport });

  instance.handleCaptured({
    source: "fetch",
    url: "https://www.fantrax.com/fxea/general/getAdp",
    method: "GET",
    status: 200,
    ok: true,
    raw: "{}",
  });
  await flushMicrotasks();

  assert.equal(sent.length, 0);
});

test("handleCaptured dedupes an identical consecutive capture but forwards a changed one", async () => {
  const capture = await loadCapture();
  const sent = [];
  const transport = { sendPayload: async (envelope) => sent.push(envelope) };
  const instance = capture.createCapture({ transport });

  const details = {
    source: "xhr",
    url: "/fxpa/req?method=getStandings",
    method: "POST",
    status: 200,
    ok: true,
    raw: '{"rank":1}',
  };
  instance.handleCaptured(details);
  instance.handleCaptured({ ...details }); // identical repeat
  instance.handleCaptured({ ...details, raw: '{"rank":2}' }); // genuinely changed
  await flushMicrotasks();

  assert.equal(sent.length, 2);
  assert.deepEqual(toPlain(sent[0].body.json), { rank: 1 });
  assert.deepEqual(toPlain(sent[1].body.json), { rank: 2 });
});

test("a failing transport.sendPayload does not throw or reject unhandled", async () => {
  const capture = await loadCapture();
  const warnings = [];
  const transport = { sendPayload: async () => { throw new Error("backend unreachable"); } };
  const instance = capture.createCapture({
    transport,
    logger: { warn: (msg) => warnings.push(msg) },
  });

  assert.doesNotThrow(() => {
    instance.handleCaptured({
      source: "fetch",
      url: "/fxpa/req",
      method: "GET",
      status: 200,
      ok: true,
      raw: "{}",
    });
  });
  await flushMicrotasks();

  assert.equal(warnings.length, 1);
  assert.match(warnings[0], /failed to forward captured payload/);
});

test("a failed delivery may retry on a later event without an internal retry loop", async () => {
  const capture = await loadCapture();
  let attempts = 0;
  let backendAvailable = false;
  const transport = {
    sendPayload: async () => {
      attempts += 1;
      if (!backendAvailable) {
        throw new Error("backend unreachable");
      }
    },
  };
  const instance = capture.createCapture({
    transport,
    logger: { warn: () => {} },
  });
  const details = {
    source: "fetch",
    url: "/fxpa/req",
    method: "GET",
    status: 200,
    ok: true,
    raw: "{}",
  };

  instance.handleCaptured(details);
  await flushMicrotasks();
  assert.equal(attempts, 1);

  backendAvailable = true;
  instance.handleCaptured(details);
  await flushMicrotasks();
  assert.equal(attempts, 2);
});

test("handleCaptured swallows an internal error instead of throwing into the page", async () => {
  const capture = await loadCapture();
  const warnings = [];
  const instance = capture.createCapture({
    transport: { sendPayload: async () => {} },
    logger: { warn: (msg) => warnings.push(msg) },
    now: () => {
      throw new Error("clock unavailable");
    },
  });

  assert.doesNotThrow(() => {
    instance.handleCaptured({ source: "fetch", url: "/fxpa/req", method: "GET", status: 200, ok: true, raw: "{}" });
  });
  assert.equal(warnings.length, 1);
  assert.match(warnings[0], /capture failed/);
});

// ---------------------------------------------------------------------------
// fetch capture wiring
// ---------------------------------------------------------------------------

test("installFetch forwards a matching response and leaves the resolved value intact", async () => {
  const capture = await loadCapture();
  const sent = [];
  const transport = { sendPayload: async (envelope) => sent.push(envelope) };
  const instance = capture.createCapture({ transport });

  const response = fakeResponse({ body: '{"ok":true}' });
  const win = { fetch: async () => response };
  instance.installFetch(win);

  const result = await win.fetch("https://www.fantrax.com/fxpa/req?method=getLeagueInfo", { method: "POST" });
  assert.equal(result, response, "the page must still receive the real, unmodified response");
  await flushMicrotasks();

  assert.equal(sent.length, 1);
  assert.equal(sent[0].source, "fetch");
  assert.equal(sent[0].request.method, "POST");
  assert.deepEqual(toPlain(sent[0].body.json), { ok: true });
});

test("installFetch does not capture responses from non-matching URLs", async () => {
  const capture = await loadCapture();
  const sent = [];
  const transport = { sendPayload: async (envelope) => sent.push(envelope) };
  const instance = capture.createCapture({ transport });

  const win = { fetch: async () => fakeResponse({ body: "{}" }) };
  instance.installFetch(win);

  await win.fetch("https://www.fantrax.com/fxea/general/getAdp");
  await flushMicrotasks();

  assert.equal(sent.length, 0);
});

test("installFetch survives a response whose clone().text() rejects", async () => {
  const capture = await loadCapture();
  const warnings = [];
  const transport = { sendPayload: async () => {} };
  const instance = capture.createCapture({ transport, logger: { warn: (m) => warnings.push(m) } });

  const badResponse = {
    status: 200,
    ok: true,
    headers: { get: () => "application/json" },
    clone() {
      return { text: async () => { throw new Error("stream already consumed"); } };
    },
  };
  const win = { fetch: async () => badResponse };
  instance.installFetch(win);

  const result = await win.fetch("/fxpa/req");
  assert.equal(result, badResponse);
  await flushMicrotasks();

  assert.equal(warnings.length, 1);
  assert.match(warnings[0], /could not read fetch response body/);
});

test("installFetch returns an uninstall function that restores the original fetch", async () => {
  const capture = await loadCapture();
  const instance = capture.createCapture({ transport: { sendPayload: async () => {} } });
  const originalFetch = async () => fakeResponse();
  const win = { fetch: originalFetch };

  const uninstall = instance.installFetch(win);
  assert.notEqual(win.fetch, originalFetch);
  uninstall();
  assert.equal(win.fetch, originalFetch);
});

// ---------------------------------------------------------------------------
// XHR capture wiring
// ---------------------------------------------------------------------------

function makeFakeXHRClass() {
  class FakeXHR {
    constructor() {
      this.status = 0;
      this.responseText = "";
      this._listeners = {};
    }
    open(method, url) {
      this._method = method;
      this._url = url;
    }
    send() {}
    addEventListener(type, handler) {
      this._listeners[type] = this._listeners[type] || [];
      this._listeners[type].push(handler);
    }
    getResponseHeader(name) {
      return name.toLowerCase() === "content-type" ? "application/json" : null;
    }
    triggerLoad(status, responseText) {
      this.status = status;
      this.responseText = responseText;
      (this._listeners.load || []).forEach((handler) => handler());
    }
  }
  return FakeXHR;
}

test("installXHR forwards a matching response captured via the load event", async () => {
  const capture = await loadCapture();
  const sent = [];
  const transport = { sendPayload: async (envelope) => sent.push(envelope) };
  const instance = capture.createCapture({ transport });

  const FakeXHR = makeFakeXHRClass();
  const win = { XMLHttpRequest: FakeXHR };
  instance.installXHR(win);

  const xhr = new win.XMLHttpRequest();
  xhr.open("POST", "/fxpa/req?method=getRosterInfo");
  xhr.triggerLoad(200, '{"roster":[]}');
  await flushMicrotasks();

  assert.equal(sent.length, 1);
  assert.equal(sent[0].source, "xhr");
  assert.equal(sent[0].request.method, "POST");
  assert.deepEqual(toPlain(sent[0].body.json), { roster: [] });
});

test("installXHR ignores a non-matching URL and preserves the page's own load listener", async () => {
  const capture = await loadCapture();
  const sent = [];
  const transport = { sendPayload: async (envelope) => sent.push(envelope) };
  const instance = capture.createCapture({ transport });

  const FakeXHR = makeFakeXHRClass();
  const win = { XMLHttpRequest: FakeXHR };
  instance.installXHR(win);

  const xhr = new win.XMLHttpRequest();
  let pageSawLoad = false;
  xhr.addEventListener("load", () => {
    pageSawLoad = true;
  });
  xhr.open("GET", "/fxea/general/getAdp");
  xhr.triggerLoad(200, "{}");
  await flushMicrotasks();

  assert.equal(sent.length, 0);
  assert.equal(pageSawLoad, true, "the page's own listener must still fire");
});

test("installXHR returns an uninstall function that restores the original XMLHttpRequest", async () => {
  const capture = await loadCapture();
  const instance = capture.createCapture({ transport: { sendPayload: async () => {} } });
  const FakeXHR = makeFakeXHRClass();
  const win = { XMLHttpRequest: FakeXHR };

  const uninstall = instance.installXHR(win);
  assert.notEqual(win.XMLHttpRequest, FakeXHR);
  uninstall();
  assert.equal(win.XMLHttpRequest, FakeXHR);
});

// ---------------------------------------------------------------------------
// Page-world bridge
// ---------------------------------------------------------------------------

function makeMessageWindow() {
  const listeners = new Map();
  return {
    location: { origin: "https://www.fantrax.com", href: "https://www.fantrax.com/fantasy/league/abc" },
    addEventListener(type, handler) {
      listeners.set(type, handler);
    },
    removeEventListener(type, handler) {
      if (listeners.get(type) === handler) {
        listeners.delete(type);
      }
    },
    emitMessage(event) {
      listeners.get("message")?.(event);
    },
  };
}

test("page-world hook observes matching fetch and XHR responses without exposing request data", async () => {
  const capture = await loadCapture();
  const published = [];
  const FakeXHR = makeFakeXHRClass();
  const pageWindow = {
    location: { origin: "https://www.fantrax.com", href: "https://www.fantrax.com/fantasy/league/abc" },
    fetch: async () => fakeResponse({ body: '{"players":[]}' }),
    XMLHttpRequest: FakeXHR,
    postMessage: (message, targetOrigin) => published.push({ message, targetOrigin }),
  };
  pageWindow.window = pageWindow;
  const source = capture.createPageWorldHookSource("test-channel");
  assert.doesNotMatch(source, /127\.0\.0\.1|Bridge-Secret|GM_xmlhttpRequest/i);
  vm.runInNewContext(source, { window: pageWindow, URL });

  const response = await pageWindow.fetch("/fxpa/req?method=getPlayers", { method: "POST", body: "never read" });
  assert.equal(response.status, 200, "the real page response remains intact");
  const xhr = new pageWindow.XMLHttpRequest();
  xhr.open("POST", "/fxpa/req?method=getRoster");
  xhr.triggerLoad(200, '{"roster":[]}');
  await flushMicrotasks();

  assert.equal(published.length, 2);
  for (const { message, targetOrigin } of published) {
    assert.equal(targetOrigin, "https://www.fantrax.com");
    assert.equal(message.schema, capture.PAGE_EVENT_SCHEMA);
    assert.equal(message.channel, "test-channel");
    assert.deepEqual(Object.keys(message).sort(), [
      "channel", "contentType", "method", "ok", "raw", "schema", "source", "status", "url",
    ]);
    assert.equal("body" in message, false);
    assert.equal("headers" in message, false);
  }
  assert.equal(published[0].message.source, "fetch");
  assert.equal(published[1].message.source, "xhr");
});

test("page-world hook ignores lookalike and off-host requests", async () => {
  const capture = await loadCapture();
  const published = [];
  const pageWindow = {
    location: { origin: "https://www.fantrax.com", href: "https://www.fantrax.com/fantasy/league/abc" },
    fetch: async () => fakeResponse({ body: "{}" }),
    postMessage: (message) => published.push(message),
  };
  pageWindow.window = pageWindow;
  vm.runInNewContext(capture.createPageWorldHookSource("test-channel"), { window: pageWindow, URL });

  await pageWindow.fetch("/fxpa/req/extra");
  await pageWindow.fetch("https://example.test/fxpa/req");
  await flushMicrotasks();
  assert.equal(published.length, 0);
});

test("isolated receiver forwards only a valid same-window, same-origin page event", async () => {
  const capture = await loadCapture();
  const sent = [];
  const win = makeMessageWindow();
  const instance = capture.createCapture({ transport: { sendPayload: async (envelope) => sent.push(envelope) } });
  const bridge = capture.installPageWorldBridge({
    capture: instance,
    win,
    doc: { documentElement: {} },
    channel: "private-channel",
    addElement: (_parent, tag, attributes) => {
      assert.equal(tag, "script");
      assert.match(attributes.textContent, /private-channel/);
      return undefined;
    },
  });
  assert.equal(bridge.installed, true);

  const valid = {
    schema: capture.PAGE_EVENT_SCHEMA,
    channel: "private-channel",
    source: "fetch",
    url: "https://www.fantrax.com/fxpa/req?method=getLeague",
    method: "POST",
    status: 200,
    ok: true,
    contentType: "application/json",
    raw: '{"league":{}}',
  };
  win.emitMessage({ source: {}, origin: win.location.origin, data: valid }); // wrong source
  win.emitMessage({ source: win, origin: "https://evil.example", data: valid }); // wrong origin
  win.emitMessage({ source: win, origin: win.location.origin, data: { ...valid, channel: "wrong" } });
  win.emitMessage({ source: win, origin: win.location.origin, data: { ...valid, raw: { not: "text" } } });
  win.emitMessage({ source: win, origin: win.location.origin, data: { ...valid, url: "/fxpa/req/extra" } });
  win.emitMessage({ source: win, origin: win.location.origin, data: valid });
  await flushMicrotasks();

  assert.equal(sent.length, 1);
  assert.equal(sent[0].request.url, valid.url);
  bridge.uninstall();
  win.emitMessage({ source: win, origin: win.location.origin, data: { ...valid, raw: '{"second":true}' } });
  await flushMicrotasks();
  assert.equal(sent.length, 1, "uninstall removes the untrusted page event receiver");
});

// ---------------------------------------------------------------------------
// Cache Storage watcher: best-effort observation of service-worker-owned
// /fxpa/req responses that fetch/XHR patching structurally cannot see.
// ---------------------------------------------------------------------------

function makeFakeCacheStorage(records) {
  // records: [{ name, entries: [{ url, method, status, ok, contentType, raw }] }]
  return {
    keys: async () => records.map((record) => record.name),
    open: async (name) => {
      const record = records.find((candidate) => candidate.name === name);
      return {
        keys: async () => (record ? record.entries.map((entry) => ({ url: entry.url, method: entry.method })) : []),
        match: async (request) => {
          const entry = record && record.entries.find((candidate) => candidate.url === request.url);
          return entry
            ? fakeResponse({ status: entry.status, ok: entry.ok, contentType: entry.contentType, body: entry.raw })
            : undefined;
        },
      };
    },
  };
}

async function flushDeepMicrotasks() {
  // The Cache Storage poll chains several nested promises (keys -> open ->
  // keys -> match -> text -> publish); one macrotask tick reliably drains all
  // of them since Node processes the whole microtask queue before a timer.
  await new Promise((resolve) => setTimeout(resolve, 0));
  await new Promise((resolve) => setTimeout(resolve, 0));
}

test("page-world hook observes a matching Cache Storage entry the fetch/XHR patch could never see", async () => {
  const capture = await loadCapture();
  const published = [];
  const pageWindow = {
    location: { origin: "https://www.fantrax.com", href: "https://www.fantrax.com/fantasy/league/abc" },
    postMessage: (message) => published.push(message),
    setInterval: () => 1,
    caches: makeFakeCacheStorage([
      {
        name: "fx-runtime-cache",
        entries: [
          { url: "https://www.fantrax.com/fxpa/req?method=getDraftPicks", method: "POST", status: 200, ok: true, contentType: "application/json", raw: '{"picks":[1,2]}' },
          { url: "https://www.fantrax.com/other-endpoint", method: "GET", status: 200, ok: true, contentType: "application/json", raw: "{}" },
        ],
      },
    ]),
  };
  pageWindow.window = pageWindow;
  const document = { visibilityState: "visible" };
  vm.runInNewContext(capture.createPageWorldHookSource("test-channel"), { window: pageWindow, document, URL });

  await flushDeepMicrotasks();

  const cacheMessages = published.filter((message) => message.source === "cache-storage");
  assert.equal(cacheMessages.length, 1, "only the matching /fxpa/req entry is published");
  assert.equal(cacheMessages[0].url, "https://www.fantrax.com/fxpa/req?method=getDraftPicks");
  assert.equal(cacheMessages[0].raw, '{"picks":[1,2]}');
  assert.equal(cacheMessages[0].channel, "test-channel");
});

test("page-world hook skips the Cache Storage poll while the tab is hidden", async () => {
  const capture = await loadCapture();
  const published = [];
  const pageWindow = {
    location: { origin: "https://www.fantrax.com", href: "https://www.fantrax.com/fantasy/league/abc" },
    postMessage: (message) => published.push(message),
    setInterval: () => 1,
    caches: makeFakeCacheStorage([
      {
        name: "fx-runtime-cache",
        entries: [
          { url: "https://www.fantrax.com/fxpa/req?method=getDraftPicks", method: "POST", status: 200, ok: true, contentType: "application/json", raw: '{"picks":[]}' },
        ],
      },
    ]),
  };
  pageWindow.window = pageWindow;
  const document = { visibilityState: "hidden" };
  vm.runInNewContext(capture.createPageWorldHookSource("test-channel"), { window: pageWindow, document, URL });

  await flushDeepMicrotasks();
  assert.equal(published.length, 0, "a hidden tab must never be raced against Fantrax's own throttled polling");
});

test("page-world hook Cache Storage watcher never throws when caches.keys() rejects", async () => {
  const capture = await loadCapture();
  const published = [];
  const pageWindow = {
    location: { origin: "https://www.fantrax.com", href: "https://www.fantrax.com/fantasy/league/abc" },
    postMessage: (message) => published.push(message),
    setInterval: () => 1,
    caches: { keys: async () => { throw new Error("boom"); } },
  };
  pageWindow.window = pageWindow;
  const document = { visibilityState: "visible" };
  assert.doesNotThrow(() => {
    vm.runInNewContext(capture.createPageWorldHookSource("test-channel"), { window: pageWindow, document, URL });
  });
  await flushDeepMicrotasks();
  assert.equal(published.length, 0);
});

test("pageEventDetails accepts cache storage but rejects isolated-world snapshot sources", async () => {
  const capture = await loadCapture();
  const win = makeMessageWindow();
  const base = {
    schema: capture.PAGE_EVENT_SCHEMA,
    channel: "chan",
    url: "https://www.fantrax.com/fxpa/req?method=getLeague",
    method: "POST",
    status: 200,
    ok: true,
    contentType: "application/json",
    raw: "{}",
  };
  const accepted = capture.pageEventDetails(
    { source: win, origin: win.location.origin, data: { ...base, source: "cache-storage" } },
    { channel: "chan", origin: win.location.origin, source: win }
  );
  assert.ok(accepted);
  assert.equal(accepted.source, "cache-storage");

  const rejected = capture.pageEventDetails(
    { source: win, origin: win.location.origin, data: { ...base, source: "manual-export" } },
    { channel: "chan", origin: win.location.origin, source: win }
  );
  assert.equal(rejected, null, "manual-export never travels over the page postMessage channel");

  const renderedView = capture.pageEventDetails(
    { source: win, origin: win.location.origin, data: { ...base, source: "rendered-view" } },
    { channel: "chan", origin: win.location.origin, source: win }
  );
  assert.equal(renderedView, null, "rendered-view never travels over the page postMessage channel");
});

// ---------------------------------------------------------------------------
// Rendered-view and manual fallback envelopes
// ---------------------------------------------------------------------------

test("captureRenderedView is league-scoped, deduped, and carries no request data", async () => {
  const capture = await loadCapture();
  const sent = [];
  const instance = capture.createCapture({
    transport: { sendPayload: async (envelope) => sent.push(envelope) },
    now: () => 1700000000000,
  });
  const details = {
    url: "https://www.fantrax.com/fantasy/league/abc/draft",
    raw: "<main>draft board</main>",
  };

  assert.equal(instance.captureRenderedView(details), true);
  assert.equal(instance.captureRenderedView(details), true);
  assert.equal(
    instance.captureRenderedView({
      url: "https://example.test/fantasy/league/abc",
      raw: details.raw,
    }),
    false
  );
  await flushMicrotasks();

  assert.equal(sent.length, 1);
  assert.equal(sent[0].source, "rendered-view");
  assert.deepEqual(toPlain(sent[0].request), {
    method: "GET",
    url: details.url,
  });
  assert.equal(sent[0].response.status, null);
  assert.equal(sent[0].response.contentType, "text/html");
  assert.equal(sent[0].body.raw, details.raw);
  assert.equal("headers" in sent[0], false);
  assert.equal("body" in sent[0].request, false);
  assert.doesNotMatch(JSON.stringify(sent[0]), /cookie/i);
});

test("createCapture().captureManual bypasses the /fxpa/req URL filter and forwards a manual-export envelope", async () => {
  const capture = await loadCapture();
  const sent = [];
  const instance = capture.createCapture({ transport: { sendPayload: async (envelope) => sent.push(envelope) } });

  const ok = instance.captureManual({
    url: "https://www.fantrax.com/fantasy/league/abc/draft",
    contentType: "text/html",
    raw: "<div>draft board</div>",
  });
  assert.equal(ok, true);
  await flushMicrotasks();

  assert.equal(sent.length, 1);
  assert.equal(sent[0].source, "manual-export");
  assert.equal(sent[0].request.method, "GET");
  assert.equal(sent[0].request.url, "https://www.fantrax.com/fantasy/league/abc/draft");
  assert.equal(sent[0].response.status, null);
  assert.equal(sent[0].response.ok, true);
  assert.equal(sent[0].response.contentType, "text/html");
  assert.equal(sent[0].body.raw, "<div>draft board</div>");
});

test("captureManual never throws even if buildEnvelope fails internally", async () => {
  const capture = await loadCapture();
  const instance = capture.createCapture({ transport: { sendPayload: async () => {} } });
  const ok = instance.captureManual({ url: undefined, contentType: null, raw: undefined });
  assert.equal(typeof ok, "boolean");
});

// ---------------------------------------------------------------------------
// Manual DOM/app-state snapshot construction
// ---------------------------------------------------------------------------

function makeCloneableRoot() {
  const parts = [
    { tag: "script", html: "<script>evil()</script>" },
    { tag: "style", html: "<style>.x{color:red}</style>" },
    { tag: "div", html: "<div>content</div>" },
  ];
  return {
    cloneNode() {
      const cloned = parts.map((part) => ({ ...part, removed: false }));
      return {
        get outerHTML() {
          return `<div id="root">${cloned.filter((part) => !part.removed).map((part) => part.html).join("")}</div>`;
        },
        querySelectorAll(selector) {
          const wanted = selector.split(",").map((token) => token.trim());
          return cloned
            .filter((part) => wanted.includes(part.tag) && !part.removed)
            .map((part) => ({ remove: () => { part.removed = true; } }));
        },
      };
    },
  };
}

function makeDynamicRoot(readContent) {
  return {
    cloneNode() {
      return {
        querySelectorAll: () => [],
        get outerHTML() {
          return `<main>${readContent()}</main>`;
        },
      };
    },
  };
}

function makeFakeClock() {
  let current = 0;
  let nextId = 1;
  const timeouts = new Map();
  const intervals = new Map();
  return {
    now: () => current,
    setTimeout(fn, delay) {
      const id = nextId++;
      timeouts.set(id, { due: current + Math.max(0, delay), fn });
      return id;
    },
    clearTimeout(id) {
      timeouts.delete(id);
    },
    setInterval(fn, delay) {
      const id = nextId++;
      intervals.set(id, { fn, delay });
      return id;
    },
    clearInterval(id) {
      intervals.delete(id);
    },
    advance(ms) {
      const target = current + ms;
      while (true) {
        const next = Array.from(timeouts.entries())
          .filter(([, task]) => task.due <= target)
          .sort((left, right) => left[1].due - right[1].due)[0];
        if (!next) {
          break;
        }
        const [id, task] = next;
        timeouts.delete(id);
        current = task.due;
        task.fn();
      }
      current = target;
    },
    pendingTimeouts: () => timeouts.size,
    pendingIntervals: () => intervals.size,
  };
}

test("buildDomSnapshotHtml strips script/style/noscript but keeps rendered content", async () => {
  const capture = await loadCapture();
  const doc = { querySelector: (selector) => (selector === "main" ? makeCloneableRoot() : null) };
  const html = capture.buildDomSnapshotHtml(doc);
  assert.doesNotMatch(html, /<script/i);
  assert.doesNotMatch(html, /<style/i);
  assert.match(html, /<div>content<\/div>/);
});

test("buildDomSnapshotHtml truncates output past the size bound", async () => {
  const capture = await loadCapture();
  const huge = "x".repeat(600000);
  const root = {
    cloneNode: () => ({
      outerHTML: `<div>${huge}</div>`,
      querySelectorAll: () => [],
    }),
  };
  const doc = { querySelector: (selector) => (selector === "main" ? root : null) };
  const html = capture.buildDomSnapshotHtml(doc);
  assert.ok(html.length < huge.length + 200);
  assert.match(html, /truncated/);
});

test("buildDomSnapshotHtml sanitizes only the detached clone's form state", async () => {
  const capture = await loadCapture();
  let liveRootTouched = false;
  const attributes = new Set(["value", "checked", "selected"]);
  const textarea = { tagName: "TEXTAREA", textContent: "typed private text" };
  const input = {
    tagName: "INPUT",
    removeAttribute: (name) => attributes.delete(name),
  };
  textarea.removeAttribute = (name) => attributes.delete(name);
  const liveRoot = {
    querySelectorAll: () => {
      liveRootTouched = true;
      return [];
    },
    cloneNode: () => ({
      querySelectorAll: (selector) =>
        selector === "input, textarea, select, option" ? [input, textarea] : [],
      get outerHTML() {
        return `<main data-attrs="${Array.from(attributes).join(",")}"><textarea>${textarea.textContent}</textarea></main>`;
      },
    }),
  };
  const doc = { querySelector: (selector) => (selector === "main" ? liveRoot : null) };

  const html = capture.buildDomSnapshotHtml(doc);
  assert.equal(liveRootTouched, false, "the live Fantrax root must never be queried or changed");
  assert.doesNotMatch(html, /value|checked|selected|typed private text/);
});

test("selectSnapshotRoot tries main, #root, #app, body in order and falls back to documentElement", async () => {
  const capture = await loadCapture();
  const documentElement = { marker: "documentElement" };
  const body = { marker: "body" };
  const doc = { querySelector: () => null, documentElement };
  assert.equal(capture.selectSnapshotRoot(doc), documentElement);

  const docWithBody = { querySelector: (selector) => (selector === "body" ? body : null), documentElement };
  assert.equal(capture.selectSnapshotRoot(docWithBody), body);
});

test("readExposedAppState prefers the first present global and survives a throwing getter", async () => {
  const capture = await loadCapture();
  const throwing = {};
  Object.defineProperty(throwing, "__NEXT_DATA__", {
    get() {
      throw new Error("boom");
    },
  });
  throwing.__NUXT__ = { league: "abc" };
  const found = capture.readExposedAppState(throwing);
  assert.equal(found.key, "__NUXT__");
  assert.equal(found.json, JSON.stringify({ league: "abc" }));

  assert.equal(capture.readExposedAppState({}), null);
});

test("automatic rendered-view snapshot stays visible, league-scoped, bounded, and DOM-only", async () => {
  const capture = await loadCapture();
  const captured = [];
  const root = makeDynamicRoot(() => "x".repeat(200));
  const doc = {
    visibilityState: "visible",
    querySelector: (selector) => (selector === "main" ? root : null),
  };
  Object.defineProperty(doc, "cookie", {
    get() {
      throw new Error("automatic capture must never read cookies");
    },
  });
  const win = {
    location: { href: "https://www.fantrax.com/fantasy/league/abc/draft" },
  };
  const instance = {
    captureRenderedView: (details) => {
      captured.push(details);
      return true;
    },
  };

  const result = capture.captureRenderedViewSnapshot({
    capture: instance,
    win,
    doc,
    maxChars: 50,
  });
  assert.equal(result.captured, true);
  assert.equal(captured.length, 1);
  assert.equal(captured[0].url, win.location.href);
  assert.match(captured[0].raw, /truncated at 50 chars/);

  doc.visibilityState = "hidden";
  assert.equal(
    capture.captureRenderedViewSnapshot({ capture: instance, win, doc }).captured,
    false
  );
  win.location.href = "https://example.test/fantasy/league/abc";
  doc.visibilityState = "visible";
  assert.equal(
    capture.captureRenderedViewSnapshot({ capture: instance, win, doc }).captured,
    false
  );
  const frameWindow = {
    location: { href: "https://www.fantrax.com/fantasy/league/abc/draft" },
    top: {},
  };
  assert.equal(
    capture.captureRenderedViewSnapshot({
      capture: instance,
      win: frameWindow,
      doc,
    }).captured,
    false
  );
  assert.equal(captured.length, 1);
});

test("automatic watcher captures initial settle, rate-limited mutations, and SPA navigation", async () => {
  const capture = await loadCapture();
  const clock = makeFakeClock();
  const sent = [];
  let view = "initial";
  let observerCallback;
  let observerDisconnected = false;
  let observedOptions;
  class FakeMutationObserver {
    constructor(callback) {
      observerCallback = callback;
    }
    observe(_target, options) {
      observedOptions = options;
    }
    disconnect() {
      observerDisconnected = true;
    }
  }
  const root = makeDynamicRoot(() => view);
  const windowListeners = new Map();
  const documentListeners = new Map();
  const win = {
    location: { href: "https://www.fantrax.com/fantasy/league/abc/players" },
    addEventListener: (name, handler) => windowListeners.set(name, handler),
    removeEventListener: (name) => windowListeners.delete(name),
  };
  const doc = {
    readyState: "complete",
    visibilityState: "visible",
    documentElement: root,
    querySelector: (selector) => (selector === "main" ? root : null),
    addEventListener: (name, handler) => documentListeners.set(name, handler),
    removeEventListener: (name) => documentListeners.delete(name),
  };
  const transport = {
    backendOrigin: "http://127.0.0.1:8000",
    isPaired: () => true,
    sendPayload: async (envelope) => sent.push(envelope),
  };
  const instance = capture.createCapture({ transport, now: clock.now });
  const watcher = capture.installAutomaticRenderedViewCapture({
    capture: instance,
    transport,
    win,
    doc,
    MutationObserverCtor: FakeMutationObserver,
    now: clock.now,
    setTimeoutFn: clock.setTimeout,
    clearTimeoutFn: clock.clearTimeout,
    setIntervalFn: clock.setInterval,
    clearIntervalFn: clock.clearInterval,
    settleMs: 100,
    maxSettleMs: 500,
    navigationMinIntervalMs: 50,
    mutationMinIntervalMs: 1000,
    locationPollMs: 250,
  });

  assert.equal(watcher.installed, true);
  assert.deepEqual(toPlain(observedOptions), { childList: true, subtree: true });
  assert.equal(clock.pendingIntervals(), 1);
  clock.advance(99);
  await flushMicrotasks();
  assert.equal(sent.length, 0);
  clock.advance(1);
  await flushMicrotasks();
  assert.equal(sent.length, 1);
  assert.equal(sent[0].source, "rendered-view");
  assert.match(sent[0].body.raw, /initial/);

  view = "settled mutation";
  observerCallback();
  clock.advance(999);
  await flushMicrotasks();
  assert.equal(sent.length, 1, "same-view DOM churn is limited to one attempt per interval");
  clock.advance(1);
  await flushMicrotasks();
  assert.equal(sent.length, 2);
  assert.match(sent[1].body.raw, /settled mutation/);

  view = "draft route";
  win.location.href = "https://www.fantrax.com/fantasy/league/abc/draft";
  watcher.checkContext();
  clock.advance(99);
  await flushMicrotasks();
  assert.equal(sent.length, 2);
  clock.advance(1);
  await flushMicrotasks();
  assert.equal(sent.length, 3);
  assert.equal(sent[2].request.url, win.location.href);
  assert.match(sent[2].body.raw, /draft route/);

  watcher.uninstall();
  assert.equal(observerDisconnected, true);
  assert.equal(clock.pendingTimeouts(), 0);
  assert.equal(clock.pendingIntervals(), 0);
  assert.equal(windowListeners.size, 0);
});

test("automatic watcher waits for document-start DOMContentLoaded before initial capture", async () => {
  const capture = await loadCapture();
  const clock = makeFakeClock();
  const sent = [];
  const listeners = new Map();
  const root = makeDynamicRoot(() => "ready league view");
  const win = {
    location: { href: "https://www.fantrax.com/fantasy/league/abc/players" },
  };
  const doc = {
    readyState: "loading",
    visibilityState: "visible",
    documentElement: null,
    querySelector: (selector) => (selector === "main" && doc.documentElement ? root : null),
    addEventListener: (name, handler) => listeners.set(name, handler),
    removeEventListener: (name) => listeners.delete(name),
  };
  const transport = {
    backendOrigin: "http://127.0.0.1:8000",
    isPaired: () => true,
    sendPayload: async (envelope) => sent.push(envelope),
  };
  const instance = capture.createCapture({ transport, now: clock.now });
  const watcher = capture.installAutomaticRenderedViewCapture({
    capture: instance,
    transport,
    win,
    doc,
    now: clock.now,
    setTimeoutFn: clock.setTimeout,
    clearTimeoutFn: clock.clearTimeout,
    setIntervalFn: clock.setInterval,
    clearIntervalFn: clock.clearInterval,
    settleMs: 25,
    maxSettleMs: 25,
    navigationMinIntervalMs: 0,
  });
  assert.equal(watcher.installed, true);
  assert.equal(clock.pendingTimeouts(), 0);
  assert.equal(typeof listeners.get("DOMContentLoaded"), "function");

  doc.readyState = "complete";
  doc.documentElement = root;
  listeners.get("DOMContentLoaded")();
  clock.advance(25);
  await flushMicrotasks();
  assert.equal(sent.length, 1);
  assert.match(sent[0].body.raw, /ready league view/);
  watcher.uninstall();
});

test("automatic watcher requires the exact local transport and waits for pairing", async () => {
  const capture = await loadCapture();
  const root = makeDynamicRoot(() => "players");
  const baseWindow = {
    location: { href: "https://www.fantrax.com/fantasy/league/abc/players" },
  };
  const doc = {
    readyState: "complete",
    visibilityState: "visible",
    documentElement: root,
    querySelector: () => root,
  };
  assert.equal(
    capture.hasPairedLocalTransport({
      backendOrigin: "https://collector.example",
      isPaired: () => true,
    }),
    false
  );
  assert.equal(
    capture.installAutomaticRenderedViewCapture({
      capture: { captureRenderedView: () => true },
      transport: {
        backendOrigin: "https://collector.example",
        isPaired: () => true,
      },
      win: baseWindow,
      doc,
    }).installed,
    false
  );

  const clock = makeFakeClock();
  const sent = [];
  let paired = false;
  const transport = {
    backendOrigin: "http://127.0.0.1:8000",
    isPaired: () => paired,
    sendPayload: async (envelope) => sent.push(envelope),
  };
  const instance = capture.createCapture({ transport, now: clock.now });
  const watcher = capture.installAutomaticRenderedViewCapture({
    capture: instance,
    transport,
    win: baseWindow,
    doc,
    now: clock.now,
    setTimeoutFn: clock.setTimeout,
    clearTimeoutFn: clock.clearTimeout,
    setIntervalFn: clock.setInterval,
    clearIntervalFn: clock.clearInterval,
    settleMs: 10,
    maxSettleMs: 10,
    navigationMinIntervalMs: 0,
    mutationMinIntervalMs: 100,
  });
  assert.equal(watcher.installed, true);
  assert.equal(clock.pendingTimeouts(), 0);

  paired = true;
  watcher.checkContext();
  clock.advance(10);
  await flushMicrotasks();
  assert.equal(sent.length, 1);
  watcher.uninstall();
});

test("captureManualSnapshot prefers exposed app state over a DOM snapshot", async () => {
  const capture = await loadCapture();
  const sent = [];
  const instance = capture.createCapture({ transport: { sendPayload: async (envelope) => sent.push(envelope) } });
  const win = {
    location: { href: "https://www.fantrax.com/fantasy/league/abc/players" },
    __NUXT__: { players: [] },
  };
  const doc = { querySelector: () => makeCloneableRoot() };

  const result = capture.captureManualSnapshot({ capture: instance, win, doc });
  assert.equal(result.captured, true);
  assert.match(result.reason, /^app-state:/);
  await flushMicrotasks();
  assert.equal(sent.length, 1);
  assert.equal(sent[0].response.contentType, "application/json");
  assert.deepEqual(JSON.parse(sent[0].body.raw), { players: [] });
});

test("captureManualSnapshot falls back to a DOM snapshot when no app state is exposed", async () => {
  const capture = await loadCapture();
  const sent = [];
  const instance = capture.createCapture({ transport: { sendPayload: async (envelope) => sent.push(envelope) } });
  const win = { location: { href: "https://www.fantrax.com/fantasy/league/abc/draft" } };
  const doc = { querySelector: (selector) => (selector === "main" ? makeCloneableRoot() : null) };

  const result = capture.captureManualSnapshot({ capture: instance, win, doc });
  assert.equal(result.captured, true);
  assert.equal(result.reason, "dom-snapshot");
  await flushMicrotasks();
  assert.equal(sent[0].response.contentType, "text/html");
  assert.match(sent[0].body.raw, /content/);
});

test("captureManualSnapshot reports failure without throwing when nothing is exportable", async () => {
  const capture = await loadCapture();
  const instance = capture.createCapture({ transport: { sendPayload: async () => {} } });
  const win = { location: { href: "https://www.fantrax.com/fantasy/league/abc" } };
  const doc = { querySelector: () => null, documentElement: null };

  const result = capture.captureManualSnapshot({ capture: instance, win, doc });
  assert.equal(result.captured, false);
  assert.match(result.reason, /no exportable content/);
});

test("installManualCaptureMenu registers a menu command and reports the outcome via alert", async () => {
  const capture = await loadCapture();
  const sent = [];
  const instance = capture.createCapture({ transport: { sendPayload: async (envelope) => sent.push(envelope) } });
  const win = { location: { href: "https://www.fantrax.com/fantasy/league/abc/draft" } };
  const doc = { querySelector: (selector) => (selector === "main" ? makeCloneableRoot() : null) };
  let registeredLabel;
  let registeredHandler;
  const alerts = [];

  const installed = capture.installManualCaptureMenu({
    registerMenuCommand: (label, handler) => {
      registeredLabel = label;
      registeredHandler = handler;
    },
    capture: instance,
    win,
    doc,
    alert: (message) => alerts.push(message),
  });

  assert.equal(installed, true);
  assert.match(registeredLabel, /capture current fantrax view/i);
  registeredHandler();
  await flushMicrotasks();
  assert.equal(sent.length, 1);
  assert.equal(alerts.length, 1);
  assert.match(alerts[0], /captured the current page/);
});

test("installManualCaptureMenu is a no-op without a registerMenuCommand function", async () => {
  const capture = await loadCapture();
  const instance = capture.createCapture({ transport: { sendPayload: async () => {} } });
  assert.equal(capture.installManualCaptureMenu({ capture: instance }), false);
});
