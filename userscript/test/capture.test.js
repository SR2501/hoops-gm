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
