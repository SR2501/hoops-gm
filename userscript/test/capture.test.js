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

test("isFantraxDraftPage scopes only draft routes inside a Fantrax league", async () => {
  const capture = await loadCapture();
  assert.equal(
    capture.isFantraxDraftPage("https://www.fantrax.com/fantasy/league/abc/draft"),
    true
  );
  assert.equal(
    capture.isFantraxDraftPage("https://www.fantrax.com/fantasy/league/abc/draft/board"),
    true
  );
  assert.equal(
    capture.isFantraxDraftPage("https://www.fantrax.com/fantasy/league/abc/draft-history"),
    false
  );
  assert.equal(
    capture.isFantraxDraftPage("https://example.test/fantasy/league/abc/draft"),
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

test("createDedupeCache contains only explicitly acknowledged keys", async () => {
  const capture = await loadCapture();
  const cache = capture.createDedupeCache();
  assert.equal(cache.has("k1"), false);
  cache.remember("k1");
  assert.equal(cache.has("k1"), true);
  assert.equal(cache.has("k2"), false);
});

test("createDedupeCache evicts the oldest entry once past maxEntries", async () => {
  const capture = await loadCapture();
  const cache = capture.createDedupeCache({ maxEntries: 2 });
  cache.remember("k1");
  cache.remember("k2");
  cache.remember("k3"); // evicts k1
  assert.equal(cache.has("k1"), false, "k1 should have been evicted");
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

test("concurrent equivalent captures share one delivery and dedupe only after acknowledgement", async () => {
  const capture = await loadCapture();
  let attempts = 0;
  let acknowledge;
  const pending = new Promise((resolve) => {
    acknowledge = resolve;
  });
  const instance = capture.createCapture({
    transport: {
      sendPayload: async () => {
        attempts += 1;
        await pending;
      },
    },
  });
  const details = {
    url: "https://www.fantrax.com/fantasy/league/abc/draft",
    contentType: "text/html",
    raw: "<main>draft</main>",
  };

  const first = instance.captureManual(details);
  const concurrent = instance.captureManual(details);
  await flushMicrotasks();
  assert.equal(attempts, 1);
  assert.equal(instance.dedupe.size(), 0, "an in-flight request is not durably acknowledged");

  acknowledge();
  assert.equal(await first, true);
  assert.equal(await concurrent, true);
  assert.equal(instance.dedupe.size(), 1);
  assert.equal(await instance.captureManual(details), true);
  assert.equal(attempts, 1);
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
  Object.defineProperties(FakeXHR, {
    UNSENT: { value: 0, enumerable: true },
    OPENED: { value: 1, enumerable: true },
    HEADERS_RECEIVED: { value: 2, enumerable: true },
    LOADING: { value: 3, enumerable: true },
    DONE: { value: 4, enumerable: true },
  });
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

test("installXHR preserves constructor constants, prototype, and genuine instances", async () => {
  const capture = await loadCapture();
  const instance = capture.createCapture({ transport: { sendPayload: async () => {} } });
  const FakeXHR = makeFakeXHRClass();
  const win = { XMLHttpRequest: FakeXHR };

  instance.installXHR(win);
  const xhr = new win.XMLHttpRequest();

  assert.equal(win.XMLHttpRequest.UNSENT, 0);
  assert.equal(win.XMLHttpRequest.DONE, 4);
  assert.equal(win.XMLHttpRequest.prototype, FakeXHR.prototype);
  assert.equal(Object.getPrototypeOf(win.XMLHttpRequest), FakeXHR);
  assert.equal(xhr instanceof FakeXHR, true);
  assert.equal(xhr instanceof win.XMLHttpRequest, true);
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
  assert.equal(pageWindow.XMLHttpRequest.UNSENT, 0);
  assert.equal(pageWindow.XMLHttpRequest.DONE, 4);
  assert.equal(pageWindow.XMLHttpRequest.prototype, FakeXHR.prototype);
  assert.equal(Object.getPrototypeOf(pageWindow.XMLHttpRequest), FakeXHR);
  assert.equal(xhr instanceof FakeXHR, true);
  assert.equal(xhr instanceof pageWindow.XMLHttpRequest, true);
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
// Cache Storage watcher: removed 2026-08-28 after being verified empty.
//
// These tests assert the *absence* of the poller, which is the only thing an
// executable test can say about a deletion. The three tests they replace had
// become worthless in a specific way worth recording: two of them asserted
// `published.length === 0` for a hidden tab and for a rejecting `caches.keys()`,
// and both kept passing after the poller was deleted, because nothing
// publishing is exactly what a deleted poller does. A green result that
// survives the removal of the code it covers is not evidence.
// ---------------------------------------------------------------------------

function makeFakeCacheStorage(records) {
  // Retained so the "never reads Cache Storage" test can offer a store that
  // *would* yield a matching /fxpa/req entry to any reader. Asserting nothing
  // is published against an empty fake would pass for the wrong reason.
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
  // Two macrotask ticks drain any nested promise chain a poll would have
  // started, so "nothing was published" cannot be an artefact of not waiting.
  await new Promise((resolve) => setTimeout(resolve, 0));
  await new Promise((resolve) => setTimeout(resolve, 0));
}

test("page-world hook never reads Cache Storage, even when a matching entry is present", async () => {
  const capture = await loadCapture();
  const published = [];
  const cacheCalls = [];
  const backingStore = makeFakeCacheStorage([
    {
      name: "fx-runtime-cache",
      entries: [
        {
          url: "https://www.fantrax.com/fxpa/req?method=getDraftPicks",
          method: "POST",
          status: 200,
          ok: true,
          contentType: "application/json",
          raw: '{"picks":[1,2]}',
        },
      ],
    },
  ]);
  const pageWindow = {
    location: { origin: "https://www.fantrax.com", href: "https://www.fantrax.com/fantasy/league/abc" },
    postMessage: (message) => published.push(message),
    setInterval: (...args) => {
      cacheCalls.push(["setInterval", ...args.slice(1)]);
      return 1;
    },
    caches: {
      keys: (...args) => {
        cacheCalls.push(["keys", ...args]);
        return backingStore.keys();
      },
      open: (...args) => {
        cacheCalls.push(["open", ...args]);
        return backingStore.open(...args);
      },
    },
  };
  pageWindow.window = pageWindow;
  const document = { visibilityState: "visible" };
  vm.runInNewContext(capture.createPageWorldHookSource("test-channel"), { window: pageWindow, document, URL });

  await flushDeepMicrotasks();

  // The entry above is exactly what the old poller looked for, so a reader
  // that still ran would publish it. Verified absent on a live draft room on
  // 2026-08-28: Fantrax's Angular service worker declares only `assetGroups`,
  // so /fxpa/req responses are never written to Cache Storage at all.
  assert.deepEqual(cacheCalls, [], "the page-world hook must not touch window.caches or start a timer");
  assert.equal(published.length, 0, "no capture may originate from Cache Storage");
});

test("page-world hook installs no recurring timer of its own", async () => {
  const capture = await loadCapture();
  const intervals = [];
  const pageWindow = {
    location: { origin: "https://www.fantrax.com", href: "https://www.fantrax.com/fantasy/league/abc" },
    postMessage: () => {},
    setInterval: (fn, ms) => {
      intervals.push(ms);
      return intervals.length;
    },
    caches: makeFakeCacheStorage([]),
  };
  pageWindow.window = pageWindow;
  const document = { visibilityState: "visible" };
  vm.runInNewContext(capture.createPageWorldHookSource("test-channel"), { window: pageWindow, document, URL });
  await flushDeepMicrotasks();

  // A background timer competes for attention in a tab the browser may be
  // throttling, and the rendered-view path already depends on setTimeout and
  // MutationObserver firing promptly during a draft.
  assert.deepEqual(intervals, [], "the page-world hook is purely reactive to fetch/XHR");
});

test("the removal of the Cache Storage path is documented where it used to run", async () => {
  const source = await readFile(new URL("../src/capture.js", import.meta.url), "utf8");

  // The prose deliberately names `setInterval(pollCacheStorage, 5000)`, so a
  // plain substring search finds the very comment that records the removal.
  // Strip comments first, and assert against what actually executes.
  // Split on /\r?\n/ rather than "\n": this checkout is CRLF, and a trailing
  // \r is a line terminator that `.` cannot cross, so a "\n" split leaves
  // every `//` comment unstripped and quietly turns this into a no-op.
  const code = source
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .split(/\r?\n/)
    .map((line) => line.replace(/(^|\s)\/\/.*$/, "$1"))
    .join("\n");

  assert.ok(
    !/pollCacheStorage/.test(code),
    "the Cache Storage poller must be gone from the code, not merely disabled"
  );
  assert.ok(
    !/\bcaches\b/.test(code),
    "no executable line may reach for window.caches any more"
  );

  // A deleted function leaves no trace. This asserts the finding survives the
  // code, so the path is not re-added in six weeks as an obvious missing
  // capability -- it was a reasonable hypothesis that turned out to be false
  // about Fantrax, not a bug in the reader.
  assert.match(source, /Cache Storage watcher: REMOVED 2026-08-28/);
  assert.match(source, /ngsw:/, "the observed cache names are the evidence for the removal");
  assert.match(source, /assetGroups/, "the mechanism, not just the outcome, is recorded");

  // Path 3 is a different claim -- still unimplemented, still a documented
  // option -- and must not be swept up in this deletion.
  assert.match(source, /IndexedDB is the same idea but was not implemented here/);
  assert.match(source, /Left as a documented option, not code\./);
});

test("the cache-storage envelope source stays accepted even though nothing emits it", async () => {
  const capture = await loadCapture();
  const win = makeMessageWindow();

  // Removing the producer is bridge-local. Removing the value from
  // hoops-gm.bridge-payload.v1 would be a contract change: the backend
  // validates it (api/routes/bridge.py) and stored payloads may already carry
  // it. This test pins that distinction so the two are not conflated later.
  const accepted = capture.pageEventDetails(
    {
      source: win,
      origin: win.location.origin,
      data: {
        schema: capture.PAGE_EVENT_SCHEMA,
        channel: "chan",
        source: "cache-storage",
        url: "https://www.fantrax.com/fxpa/req?method=getLeague",
        method: "POST",
        status: 200,
        ok: true,
        contentType: "application/json",
        raw: "{}",
      },
    },
    { channel: "chan", origin: win.location.origin, source: win }
  );
  assert.ok(accepted, "the schema value survives the removal of its only producer");
  assert.equal(accepted.source, "cache-storage");
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

  assert.equal(await instance.captureRenderedView(details), true);
  assert.equal(await instance.captureRenderedView(details), true);
  assert.equal(
    await instance.captureRenderedView({
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

  const ok = await instance.captureManual({
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
  const ok = await instance.captureManual({ url: undefined, contentType: null, raw: undefined });
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

function makeDraftBoardRoot(readContent, { header = true, body = true } = {}) {
  return {
    cloneNode() {
      return {
        querySelectorAll: () => [],
        querySelector(selector) {
          if (selector === ".league-draft-board__header") {
            return header ? {} : null;
          }
          if (selector === ".league-draft-board__body") {
            return body ? {} : null;
          }
          return null;
        },
        get outerHTML() {
          return readContent();
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

test("buildDomSnapshotHtml ignores quotes in comments when finding a safe truncation boundary", async () => {
  const capture = await loadCapture();
  const huge = "x".repeat(600000);
  const root = {
    cloneNode: () => ({
      outerHTML: `<main><!-- " --><div data-long="safe>${huge}"><span>after</span></div></main>`,
      querySelectorAll: () => [],
    }),
  };
  const doc = { querySelector: (selector) => (selector === "main" ? root : null) };
  const html = capture.buildDomSnapshotHtml(doc);
  assert.match(html, /truncated/);
  assert.ok(html.length <= 500000, "the marker is part of the configured cap");
  const markerAt = html.indexOf("<!-- hoops-gm bridge: truncated at");
  assert.equal(
    html.slice(0, markerAt),
    '<main><!-- " -->\n',
    "the comment closes safely but the over-budget attribute tag is discarded whole"
  );
  assert.doesNotMatch(html, /data-long=/, "an over-budget opening tag is discarded whole");
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
    location: { href: "https://www.fantrax.com/fantasy/league/abc/players" },
  };
  const instance = {
    captureRenderedView: (details) => {
      captured.push(details);
      return true;
    },
  };

  const result = await capture.captureRenderedViewSnapshot({
    capture: instance,
    win,
    doc,
    maxChars: 50,
  });
  assert.equal(result.captured, true);
  assert.equal(captured.length, 1);
  assert.equal(captured[0].url, win.location.href);
  assert.match(captured[0].raw, /truncated at 50 chars/);
  assert.ok(captured[0].raw.length <= 50);

  doc.visibilityState = "hidden";
  assert.equal(
    (await capture.captureRenderedViewSnapshot({ capture: instance, win, doc })).captured,
    false
  );
  win.location.href = "https://example.test/fantasy/league/abc";
  doc.visibilityState = "visible";
  assert.equal(
    (await capture.captureRenderedViewSnapshot({ capture: instance, win, doc })).captured,
    false
  );
  const frameWindow = {
    location: { href: "https://www.fantrax.com/fantasy/league/abc/draft" },
    top: {},
  };
  assert.equal(
    (await capture.captureRenderedViewSnapshot({
      capture: instance,
      win: frameWindow,
      doc,
    })).captured,
    false
  );
  assert.equal(captured.length, 1);
});

test("automatic draft snapshot excludes navbar and chat so only the complete board spends the cap", async () => {
  const capture = await loadCapture();
  const captured = [];
  const boardHtml = [
    '<league-draft-board-table class="league-draft-board">',
    '<div class="league-draft-board__header">all seats</div>',
    '<div class="league-draft-board__body">all rounds and picks</div>',
    "</league-draft-board-table>",
  ].join("");
  const board = makeDraftBoardRoot(() => boardHtml);
  const chatHtml = `<chat-room class="chat-room">${"c".repeat(300)}</chat-room>`;
  const chat = makeDraftBoardRoot(() => chatHtml);
  const unrelatedPage = makeDynamicRoot(
    () => `<main><nav>${"n".repeat(300)}</nav>${boardHtml}${chatHtml}</main>`
  );
  const doc = {
    visibilityState: "visible",
    querySelector(selector) {
      if (selector === ".league-draft-board") {
        return board;
      }
      if (selector === ".chat-room") {
        return chat;
      }
      return selector === "main" ? unrelatedPage : null;
    },
  };
  const win = {
    location: { href: "https://www.fantrax.com/fantasy/league/abc/draft/board" },
  };
  const instance = {
    captureRenderedView: (details) => {
      captured.push(details);
      return true;
    },
  };
  const maxChars = boardHtml.length + 100;

  const result = await capture.captureRenderedViewSnapshot({
    capture: instance,
    win,
    doc,
    maxChars,
  });

  assert.equal(result.captured, true);
  assert.equal(result.reason, "rendered-view");
  assert.equal(captured.length, 1);
  assert.ok(captured[0].raw.startsWith(boardHtml));
  assert.match(captured[0].raw, /auxiliary chat omitted at/);
  assert.doesNotMatch(
    captured[0].raw,
    /hoops-gm bridge: truncated at/,
    "the backend must not misclassify later board drift as a cut grid"
  );
  assert.doesNotMatch(captured[0].raw, /<nav>|<chat-room/);
  assert.ok(captured[0].raw.length <= maxChars);
});

test("automatic draft snapshot retains chat corroboration only when it fits after the board", async () => {
  const capture = await loadCapture();
  const captured = [];
  const boardHtml = [
    '<league-draft-board-table class="league-draft-board">',
    '<div class="league-draft-board__header">all seats</div>',
    '<div class="league-draft-board__body">all rounds and picks</div>',
    "</league-draft-board-table>",
  ].join("");
  const chatHtml = [
    '<chat-room class="chat-room">',
    '<div class="chat-message__name">Seat 01 drafted - 1-1 [1]</div>',
    "</chat-room>",
  ].join("");
  const board = makeDraftBoardRoot(() => boardHtml);
  const chat = makeDraftBoardRoot(() => chatHtml);
  const result = await capture.captureRenderedViewSnapshot({
    capture: {
      captureRenderedView: (details) => {
        captured.push(details);
        return true;
      },
    },
    win: { location: { href: "https://www.fantrax.com/fantasy/league/abc/draft" } },
    doc: {
      visibilityState: "visible",
      querySelector(selector) {
        if (selector === ".league-draft-board") {
          return board;
        }
        return selector === ".chat-room" ? chat : null;
      },
    },
    maxChars: boardHtml.length + chatHtml.length + 1,
  });

  assert.equal(result.captured, true);
  assert.equal(captured[0].raw, `${boardHtml}\n${chatHtml}`);
  assert.match(captured[0].raw, /chat-message__name/);
});

test("a near-cap draft board drops chat metadata rather than exceeding the cap", async () => {
  const capture = await loadCapture();
  const boardHtml = [
    '<league-draft-board-table class="league-draft-board">',
    '<div class="league-draft-board__header">all seats</div>',
    '<div class="league-draft-board__body">all rounds and picks</div>',
    "</league-draft-board-table>",
  ].join("");
  const board = makeDraftBoardRoot(() => boardHtml);
  const chat = makeDraftBoardRoot(
    () => '<chat-room class="chat-room"><div class="chat-message__name">pick</div></chat-room>'
  );
  const html = capture.buildDraftBoardSnapshotHtml(
    {
      querySelector(selector) {
        if (selector === ".league-draft-board") {
          return board;
        }
        return selector === ".chat-room" ? chat : null;
      },
    },
    { maxChars: boardHtml.length }
  );

  assert.equal(html, boardHtml);
  assert.equal(html.length, boardHtml.length);
});

test("automatic draft snapshot refuses an over-budget board instead of sending a partial grid", async () => {
  const capture = await loadCapture();
  const captured = [];
  const warnings = [];
  const boardHtml = [
    '<league-draft-board-table class="league-draft-board">',
    '<div class="league-draft-board__header">all seats</div>',
    `<div class="league-draft-board__body">${"p".repeat(300)}</div>`,
    "</league-draft-board-table>",
  ].join("");
  const board = makeDraftBoardRoot(() => boardHtml);
  const doc = {
    visibilityState: "visible",
    querySelector: (selector) => (selector === ".league-draft-board" ? board : null),
  };
  const result = await capture.captureRenderedViewSnapshot({
    capture: {
      captureRenderedView: (details) => {
        captured.push(details);
        return true;
      },
    },
    win: { location: { href: "https://www.fantrax.com/fantasy/league/abc/draft" } },
    doc,
    logger: { warn: (message) => warnings.push(message) },
    maxChars: 250,
  });

  assert.equal(result.captured, false);
  assert.equal(result.refusal, true);
  assert.match(result.reason, /exceeding the 250-char automatic capture cap/);
  assert.match(result.reason, /no partial board was sent/);
  assert.equal(captured.length, 0);
  assert.equal(warnings.length, 1, "the refusal must be visible rather than silently skipped");
  assert.match(warnings[0], /automatic rendered-view capture failed/);
});

test("automatic draft snapshot refuses when the parser-required header is outside the board subtree", async () => {
  const capture = await loadCapture();
  const warnings = [];
  const board = makeDraftBoardRoot(
    () => '<league-draft-board-table class="league-draft-board"></league-draft-board-table>',
    { header: false }
  );
  const result = await capture.captureRenderedViewSnapshot({
    capture: { captureRenderedView: () => true },
    win: { location: { href: "https://www.fantrax.com/fantasy/league/abc/draft" } },
    doc: {
      visibilityState: "visible",
      querySelector: (selector) => (selector === ".league-draft-board" ? board : null),
    },
    logger: { warn: (message) => warnings.push(message) },
  });

  assert.equal(result.captured, false);
  assert.equal(result.refusal, true);
  assert.match(result.reason, /missing \.league-draft-board__header/);
  assert.match(result.reason, /no partial board was sent/);
  assert.equal(warnings.length, 1);
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
  const board = makeDraftBoardRoot(() => [
    '<league-draft-board-table class="league-draft-board">',
    '<div class="league-draft-board__header">all seats</div>',
    `<div class="league-draft-board__body">${view}</div>`,
    "</league-draft-board-table>",
  ].join(""));
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
    querySelector: (selector) => {
      if (selector === ".league-draft-board" && win.location.href.includes("/draft")) {
        return board;
      }
      return selector === "main" ? root : null;
    },
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

test("automatic watcher publishes an unsafe draft snapshot refusal to the status strip", async () => {
  const capture = await loadCapture();
  const clock = makeFakeClock();
  const refusals = [];
  const board = makeDraftBoardRoot(() => [
    '<league-draft-board-table class="league-draft-board">',
    '<div class="league-draft-board__header">all seats</div>',
    `<div class="league-draft-board__body">${"p".repeat(250000)}</div>`,
    "</league-draft-board-table>",
  ].join(""));
  const win = {
    location: { href: "https://www.fantrax.com/fantasy/league/abc/draft" },
    addEventListener: () => {},
    removeEventListener: () => {},
  };
  const doc = {
    readyState: "complete",
    visibilityState: "visible",
    documentElement: board,
    querySelector: (selector) => (selector === ".league-draft-board" ? board : null),
    addEventListener: () => {},
    removeEventListener: () => {},
  };
  const transport = {
    backendOrigin: "http://127.0.0.1:8000",
    isPaired: () => true,
  };
  const watcher = capture.installAutomaticRenderedViewCapture({
    capture: { captureRenderedView: () => { throw new Error("partial board was sent"); } },
    transport,
    win,
    doc,
    now: clock.now,
    setTimeoutFn: clock.setTimeout,
    clearTimeoutFn: clock.clearTimeout,
    setIntervalFn: clock.setInterval,
    clearIntervalFn: clock.clearInterval,
    settleMs: 0,
    maxSettleMs: 0,
    navigationMinIntervalMs: 0,
    mutationMinIntervalMs: 60000,
    status: {
      observeContext: () => {},
      recordRefusal: (reason) => refusals.push(reason),
    },
    logger: { warn: () => {} },
  });

  clock.advance(0);
  await flushMicrotasks();

  assert.equal(refusals.length, 1);
  assert.match(refusals[0], /no partial board was sent/);

  watcher.requestSnapshot("mutation");
  clock.advance(59999);
  await flushMicrotasks();
  assert.equal(refusals.length, 1, "a refusal is still an attempt and must be rate-limited");
  clock.advance(1);
  await flushMicrotasks();
  assert.equal(refusals.length, 2);
  watcher.uninstall();
});

test("a mutation during an in-flight snapshot is rate-limited from attempt start", async () => {
  const capture = await loadCapture();
  const clock = makeFakeClock();
  const root = makeDynamicRoot(() => "players");
  let calls = 0;
  let resolveFirst;
  const watcher = capture.installAutomaticRenderedViewCapture({
    capture: {
      captureRenderedView: () => {
        calls += 1;
        if (calls === 1) {
          return new Promise((resolve) => {
            resolveFirst = resolve;
          });
        }
        return true;
      },
    },
    transport: {
      backendOrigin: "http://127.0.0.1:8000",
      isPaired: () => true,
    },
    win: {
      location: { href: "https://www.fantrax.com/fantasy/league/abc/players" },
      addEventListener: () => {},
      removeEventListener: () => {},
    },
    doc: {
      readyState: "complete",
      visibilityState: "visible",
      documentElement: root,
      querySelector: (selector) => (selector === "main" ? root : null),
      addEventListener: () => {},
      removeEventListener: () => {},
    },
    now: clock.now,
    setTimeoutFn: clock.setTimeout,
    clearTimeoutFn: clock.clearTimeout,
    setIntervalFn: clock.setInterval,
    clearIntervalFn: clock.clearInterval,
    settleMs: 0,
    maxSettleMs: 0,
    navigationMinIntervalMs: 0,
    mutationMinIntervalMs: 60000,
  });

  clock.advance(0);
  await flushMicrotasks();
  assert.equal(calls, 1);

  watcher.requestSnapshot("mutation");
  resolveFirst(true);
  await flushMicrotasks();
  clock.advance(59999);
  await flushMicrotasks();
  assert.equal(calls, 1, "in-flight churn cannot queue an immediate second serialization");
  clock.advance(1);
  await flushMicrotasks();
  assert.equal(calls, 2);
  watcher.uninstall();
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

  const result = await capture.captureManualSnapshot({ capture: instance, win, doc });
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

  const result = await capture.captureManualSnapshot({ capture: instance, win, doc });
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

  const result = await capture.captureManualSnapshot({ capture: instance, win, doc });
  assert.equal(result.captured, false);
  assert.match(result.reason, /no exportable content/);
});

test("installManualCaptureMenu reports stored only after transport acknowledgement", async () => {
  const capture = await loadCapture();
  const sent = [];
  let acknowledge;
  const pending = new Promise((resolve) => {
    acknowledge = resolve;
  });
  const instance = capture.createCapture({
    transport: {
      sendPayload: async (envelope) => {
        sent.push(envelope);
        await pending;
      },
    },
  });
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
  assert.equal(alerts.length, 0, "the UI must not claim storage while transport is pending");

  acknowledge();
  await flushMicrotasks();
  assert.equal(alerts.length, 1);
  assert.match(alerts[0], /stored the current page/);
});

test("manual capture reports failure and permits a later retry", async () => {
  const capture = await loadCapture();
  let attempts = 0;
  const instance = capture.createCapture({
    transport: {
      sendPayload: async () => {
        attempts += 1;
        if (attempts === 1) {
          throw new Error("backend returned HTTP 500");
        }
      },
    },
    logger: { warn: () => {} },
  });
  const win = { location: { href: "https://www.fantrax.com/fantasy/league/abc/draft" } };
  const doc = { querySelector: (selector) => (selector === "main" ? makeCloneableRoot() : null) };
  const alerts = [];
  let registeredHandler;

  capture.installManualCaptureMenu({
    registerMenuCommand: (_label, handler) => {
      registeredHandler = handler;
    },
    capture: instance,
    win,
    doc,
    alert: (message) => alerts.push(message),
  });

  registeredHandler();
  await flushMicrotasks();
  assert.match(alerts[0], /nothing stored/);

  registeredHandler();
  await flushMicrotasks();
  assert.equal(attempts, 2);
  assert.match(alerts[1], /stored the current page/);
});

test("installManualCaptureMenu is a no-op without a registerMenuCommand function", async () => {
  const capture = await loadCapture();
  const instance = capture.createCapture({ transport: { sendPayload: async () => {} } });
  assert.equal(capture.installManualCaptureMenu({ capture: instance }), false);
});

// ---------------------------------------------------------------------------
// Status strip: making the bridge's four silent failures visible on the page
// the owner is already looking at.
// ---------------------------------------------------------------------------

function makeStripNode(tagName) {
  const node = {
    tagName,
    children: [],
    parentNode: null,
    styleWrites: [],
    textWrites: [],
    shadowMode: null,
    shadowRoot: null,
    _text: "",
    style: {
      values: new Map(),
      setProperty(name, value) {
        node.styleWrites.push([name, value]);
        this.values.set(name, value);
      },
      getPropertyValue(name) {
        return this.values.has(name) ? this.values.get(name) : "";
      },
    },
    get textContent() {
      return node._text;
    },
    set textContent(value) {
      node._text = value;
      node.textWrites.push(value);
    },
    // The strip renders capture-derived text. Parsing any of it as markup
    // would turn a refusal message into a script injection vector, so the
    // fake refuses to have an innerHTML at all.
    set innerHTML(_value) {
      throw new Error("the status strip must never assign innerHTML");
    },
    appendChild(child) {
      node.children.push(child);
      child.parentNode = node;
      return child;
    },
    attachShadow({ mode } = {}) {
      node.shadowMode = mode;
      node.shadowRoot = {
        host: node,
        children: [],
        appendChild(child) {
          this.children.push(child);
          return child;
        },
      };
      return node.shadowRoot;
    },
    remove() {
      if (node.parentNode) {
        node.parentNode.children = node.parentNode.children.filter((entry) => entry !== node);
        node.parentNode = null;
      }
    },
  };
  return node;
}

function makeStripDocument({ withBody = true } = {}) {
  const created = [];
  const listeners = new Map();
  return {
    readyState: withBody ? "complete" : "loading",
    visibilityState: "visible",
    body: withBody ? makeStripNode("body") : null,
    documentElement: makeStripNode("html"),
    created,
    listeners,
    createElement(tagName) {
      const node = makeStripNode(tagName);
      created.push(node);
      return node;
    },
    addEventListener(type, handler) {
      listeners.set(type, handler);
    },
    removeEventListener(type) {
      listeners.delete(type);
    },
    fire(type) {
      const handler = listeners.get(type);
      if (handler) {
        handler();
      }
    },
  };
}

function makeStripWindow(href = "https://www.fantrax.com/fantasy/league/abc/draft") {
  return { location: { href } };
}

function stripNodes(strip) {
  const box = strip.shadowRoot.children[0];
  return { box, headline: box.children[0], detail: box.children[1], refusal: box.children[2] };
}

test("sanitizeStatusText redacts secret-shaped tokens, collapses whitespace, and truncates", async () => {
  const capture = await loadCapture();

  assert.equal(capture.sanitizeStatusText("  backend\n unreachable  "), "backend unreachable");
  assert.equal(capture.sanitizeStatusText(""), null);
  assert.equal(capture.sanitizeStatusText("   "), null);
  assert.equal(capture.sanitizeStatusText(undefined), null);

  // No transport rejection in userscript.js carries the bridge secret, but
  // this is the one capture-derived string that reaches the DOM, so the
  // guarantee is enforced rather than inherited from every future error path.
  const hexSecret = "a".repeat(32) + "b".repeat(32);
  const redactedHex = capture.sanitizeStatusText(`rejected ${hexSecret}`);
  assert.equal(redactedHex, "rejected [redacted]");
  assert.ok(!redactedHex.includes(hexSecret));

  const base64Secret = "Ab3" + "x".repeat(40);
  const redactedBase64 = capture.sanitizeStatusText(`rejected ${base64Secret}`);
  assert.ok(!redactedBase64.includes(base64Secret), "base64url-shaped secrets are redacted too");

  // A long unbroken alphanumeric run is itself secret-shaped, so truncation
  // has to be exercised with text that survives redaction.
  const long = capture.sanitizeStatusText("backend unreachable ".repeat(40));
  assert.equal(long.length, 120);
  assert.ok(long.endsWith("\u2026"));
  assert.ok(long.startsWith("backend unreachable"));
});

test("formatStatusLines separates the four ways this bridge fails silently", async () => {
  const capture = await loadCapture();
  const base = {
    version: "0.5.2",
    paired: true,
    forwarded: 0,
    duplicates: 0,
    lastCaptureAtMs: null,
    lastSource: null,
    lastRefusal: null,
  };
  const at = 1_000_000;

  // 1. Unpaired. Advice, never a block -- the page keeps working either way.
  const unpaired = capture.formatStatusLines({ ...base, paired: false }, { nowMs: at });
  assert.match(unpaired.headline, /NOT PAIRED/);
  assert.match(unpaired.detail, /pair from the Tampermonkey menu/);
  assert.equal(unpaired.ok, false);

  // 2. Paired but nothing captured -- a draft that has not started.
  const idle = capture.formatStatusLines(base, { nowMs: at });
  assert.match(idle.headline, /paired/);
  assert.equal(idle.detail, "no captures yet");
  assert.equal(idle.refusal, null);
  assert.equal(idle.ok, true);

  // 3. A refused envelope. Previously the reason was discarded in forward()'s
  //    catch, which made this indistinguishable from case 2 on the page.
  const refused = capture.formatStatusLines(
    { ...base, lastRefusal: "backend returned HTTP 401" },
    { nowMs: at }
  );
  assert.equal(refused.refusal, "refused: backend returned HTTP 401");
  assert.equal(refused.ok, false);

  // 4. A stale build. On 2026-08-28 the browser truthfully reported "no
  //    update available" for an artifact ten days older than the source that
  //    declared it; the running @version is the only thing that says so.
  assert.match(capture.formatStatusLines({ ...base, version: "0.4.0" }, { nowMs: at }).headline, /v0\.4\.0/);
  assert.match(capture.formatStatusLines({ ...base, version: null }, { nowMs: at }).headline, /hoops-gm bridge/);
});

test("formatStatusLines reports counts, source and a coarse age", async () => {
  const capture = await loadCapture();
  const capturedAt = 1_000_000;
  const state = {
    version: "0.5.2",
    paired: true,
    forwarded: 3,
    duplicates: 2,
    lastCaptureAtMs: capturedAt,
    lastSource: "rendered-view",
    lastRefusal: null,
  };

  const fresh = capture.formatStatusLines(state, { nowMs: capturedAt + 5_000 });
  assert.match(fresh.detail, /^3 sent/);
  // "Captured, byte-identical to one already sent" is a different fact from
  // "captured nothing": on a draft board it means the view has not changed.
  assert.match(fresh.detail, /2 unchanged/);
  assert.match(fresh.detail, /\d{2}:\d{2}:\d{2} \(just now\)/);
  // Which path produced it is load-bearing: /fxpa/req is unreachable, so a
  // healthy count made entirely of rendered-view snapshots is expected, not
  // evidence that RPC capture is working.
  assert.match(fresh.detail, /rendered-view$/);

  assert.match(
    capture.formatStatusLines(state, { nowMs: capturedAt + 300_000 }).detail,
    /\(5m ago\)/
  );
  assert.match(
    capture.formatStatusLines(state, { nowMs: capturedAt + 7_200_000 }).detail,
    /\(2h ago\)/
  );

  // Coarse on purpose: a per-second age would rewrite the DOM every second
  // for the whole draft. Two nearby instants must render identically.
  assert.deepEqual(
    capture.formatStatusLines(state, { nowMs: capturedAt + 1_000 }),
    capture.formatStatusLines(state, { nowMs: capturedAt + 2_000 })
  );
});

test("formatStatusLines never renders a number a decision rests on", async () => {
  const capture = await loadCapture();
  // The hard boundary from the backlog item: a price, a value, a suggested
  // bid or a ranking belongs to bridge-overlay and carries the Model gate
  // with it. If one appears here this has become the wrong component.
  const forbidden = /\$|\bprice[sd]?\b|\bbids?\b|\brank(ing|ed|s)?\b|\bvalues?\b|\bprojection|\bz-?score|\btier\b|\bADP\b/i;
  const states = [
    { version: "0.5.2", paired: false, forwarded: 0, duplicates: 0, lastCaptureAtMs: null, lastSource: null, lastRefusal: null },
    { version: "0.5.2", paired: true, forwarded: 0, duplicates: 0, lastCaptureAtMs: null, lastSource: null, lastRefusal: null },
    { version: "0.5.2", paired: true, forwarded: 9, duplicates: 4, lastCaptureAtMs: 5_000, lastSource: "manual-export", lastRefusal: null },
    { version: null, paired: true, forwarded: 1, duplicates: 0, lastCaptureAtMs: 5_000, lastSource: "rendered-view", lastRefusal: "backend unreachable" },
  ];

  for (const state of states) {
    const lines = capture.formatStatusLines(state, { nowMs: 60_000 });
    const rendered = `${lines.headline} ${lines.detail} ${lines.refusal || ""}`;
    assert.ok(!forbidden.test(rendered), `status text must carry no valuation vocabulary: ${rendered}`);
  }
});

test("createBridgeStatus records deliveries, duplicates and refusals, and notifies once each", async () => {
  const capture = await loadCapture();
  let clock = 1_000;
  const status = capture.createBridgeStatus({ version: "0.5.2", now: () => clock });
  const seen = [];
  const unsubscribe = status.subscribe((state) => seen.push(state));

  assert.equal(seen.length, 1, "subscribing renders the current state immediately");
  assert.deepEqual(
    { forwarded: seen[0].forwarded, duplicates: seen[0].duplicates, paired: seen[0].paired },
    { forwarded: 0, duplicates: 0, paired: false }
  );

  status.observeContext({ paired: true });
  status.recordDelivered("rendered-view");
  assert.equal(status.snapshot().forwarded, 1);
  assert.equal(status.snapshot().lastCaptureAtMs, 1_000);
  assert.equal(status.snapshot().lastSource, "rendered-view");

  clock = 2_000;
  status.recordDuplicate("rendered-view");
  assert.equal(status.snapshot().duplicates, 1);
  assert.equal(status.snapshot().lastCaptureAtMs, 2_000);
  assert.equal(status.snapshot().forwarded, 1, "a duplicate is not a new delivery");

  clock = 3_000;
  status.recordRefusal("backend returned HTTP 401");
  assert.equal(status.snapshot().lastRefusal, "backend returned HTTP 401");
  assert.equal(status.snapshot().lastRefusalAtMs, 3_000);

  // A later success clears the refusal: a stale "refused" banner over a feed
  // that has recovered is its own silent failure.
  clock = 4_000;
  status.recordDelivered("manual-export");
  assert.equal(status.snapshot().lastRefusal, null);
  assert.equal(status.snapshot().lastRefusalAtMs, null);

  assert.equal(seen.length, 6);
  unsubscribe();
  status.recordDelivered("rendered-view");
  assert.equal(seen.length, 6, "unsubscribe detaches the renderer");
});

test("createBridgeStatus keeps an unreadable message from reaching the strip verbatim", async () => {
  const capture = await loadCapture();
  const status = capture.createBridgeStatus({ now: () => 1 });
  const secret = "c".repeat(64);

  status.recordRefusal(`boom ${secret}`);
  assert.equal(status.snapshot().lastRefusal, "boom [redacted]");

  status.recordRefusal(undefined);
  assert.equal(status.snapshot().lastRefusal, "unknown error");
});

test("createCapture reports delivery, duplication and the refusal reason to the status store", async () => {
  const capture = await loadCapture();
  let clock = 10;
  const status = capture.createBridgeStatus({ version: "0.5.2", now: () => clock });
  let failNext = false;
  const transport = {
    backendOrigin: "http://127.0.0.1:8000",
    isPaired: () => true,
    sendPayload: async () => {
      if (failNext) {
        throw new Error("backend returned HTTP 401");
      }
      return { status: "stored", id: 1 };
    },
  };
  const instance = capture.createCapture({
    transport,
    status,
    now: () => clock,
    logger: { warn() {} },
  });

  const details = {
    source: "fetch",
    url: "https://www.fantrax.com/fxpa/req?method=getLeagueInfo",
    method: "POST",
    status: 200,
    ok: true,
    contentType: "application/json",
    raw: '{"picks":1}',
  };
  instance.handleCaptured(details);
  await flushMicrotasks();
  assert.equal(status.snapshot().forwarded, 1);
  assert.equal(status.snapshot().lastSource, "fetch");

  // Byte-identical replay: captured, deduped, and reported as such.
  instance.handleCaptured(details);
  await flushMicrotasks();
  assert.equal(status.snapshot().duplicates, 1);
  assert.equal(status.snapshot().forwarded, 1);

  failNext = true;
  clock = 20;
  instance.handleCaptured({ ...details, raw: '{"picks":2}' });
  await flushMicrotasks();
  assert.equal(status.snapshot().lastRefusal, "backend returned HTTP 401");
  assert.equal(status.snapshot().forwarded, 1, "a refused envelope is never counted as sent");
});

test("a status store that throws can never break capture", async () => {
  const capture = await loadCapture();
  const sent = [];
  const transport = {
    backendOrigin: "http://127.0.0.1:8000",
    isPaired: () => true,
    sendPayload: async (envelope) => sent.push(envelope),
  };
  const hostile = {
    subscribe: () => () => {},
    snapshot: () => ({}),
    recordDelivered() {
      throw new Error("strip exploded");
    },
    recordDuplicate() {
      throw new Error("strip exploded");
    },
    recordRefusal() {
      throw new Error("strip exploded");
    },
    observeContext() {
      throw new Error("strip exploded");
    },
  };
  const instance = capture.createCapture({ transport, status: hostile, logger: { warn() {} } });

  instance.handleCaptured({
    source: "fetch",
    url: "https://www.fantrax.com/fxpa/req?method=getLeagueInfo",
    method: "POST",
    status: 200,
    ok: true,
    contentType: "application/json",
    raw: "{}",
  });
  await flushMicrotasks();

  assert.equal(sent.length, 1, "the payload still reached the backend");
});

test("installStatusStrip renders into a closed shadow root that cannot intercept a click", async () => {
  const capture = await loadCapture();
  const win = makeStripWindow();
  const doc = makeStripDocument();
  const status = capture.createBridgeStatus({ version: "0.5.2", now: () => 1_000 });

  const strip = capture.installStatusStrip({ status, win, doc, now: () => 1_000 });
  assert.equal(strip.installed, true);

  // Closed, so Fantrax's own page script cannot reach in through
  // element.shadowRoot; and shadow-scoped, so their Angular styles cannot
  // restyle it and nothing here leaks into their page.
  assert.equal(strip.host.shadowMode, "closed");
  assert.equal(doc.body.children[0], strip.host, "the strip mounts into the page body");

  // Advise everywhere, override nowhere: with pointer events off the strip is
  // structurally incapable of swallowing a click meant for the draft board.
  assert.equal(strip.host.style.getPropertyValue("pointer-events"), "none");
  assert.equal(strip.host.style.getPropertyValue("position"), "fixed");

  // `all: initial` must be written first, or the resets it performs would
  // wipe the positioning written before it.
  assert.deepEqual(strip.host.styleWrites[0], ["all", "initial"]);

  // A <style> element or a style attribute would be blocked by a style-src
  // CSP on fantrax.com and leave an invisible strip; CSSOM writes are not.
  assert.deepEqual(
    doc.created.filter((node) => node.tagName.toLowerCase() === "style"),
    []
  );
  assert.ok(doc.created.every((node) => node.styleWrites.length >= 0));

  const { headline, detail } = stripNodes(strip);
  assert.match(headline.textContent, /hoops-gm v0\.5\.2 \u00b7 NOT PAIRED/);
  assert.match(detail.textContent, /pair from the Tampermonkey menu/);
});

test("the status strip re-renders on real transitions and stays silent otherwise", async () => {
  const capture = await loadCapture();
  const win = makeStripWindow();
  const doc = makeStripDocument();
  let clock = 1_000;
  const status = capture.createBridgeStatus({ version: "0.5.2", now: () => clock });
  const strip = capture.installStatusStrip({ status, win, doc, now: () => clock });
  const { headline, detail, refusal } = stripNodes(strip);

  assert.equal(headline.textWrites.length, 1);

  // The watcher tick calls observeContext once a second for a whole draft.
  // An unchanged tick must not mutate the DOM Fantrax is also mutating.
  status.observeContext({ paired: false });
  status.observeContext({ paired: false });
  assert.equal(headline.textWrites.length, 1, "an unchanged tick writes nothing");

  status.observeContext({ paired: true });
  assert.equal(headline.textWrites.length, 2);
  assert.match(headline.textContent, /\u00b7 paired$/);
  assert.equal(detail.textContent, "no captures yet");

  status.recordDelivered("rendered-view");
  assert.match(detail.textContent, /1 sent/);
  assert.equal(refusal.style.getPropertyValue("display"), "none");

  clock = 2_000;
  status.recordRefusal("backend unreachable");
  assert.equal(refusal.textContent, "refused: backend unreachable");
  assert.equal(refusal.style.getPropertyValue("display"), "block");
});

test("the status strip writes text, never markup", async () => {
  const capture = await loadCapture();
  const win = makeStripWindow();
  const doc = makeStripDocument();
  const status = capture.createBridgeStatus({ version: "0.5.2", now: () => 1 });
  const strip = capture.installStatusStrip({ status, win, doc, now: () => 1 });

  // makeStripNode throws on any innerHTML assignment. A refusal message is
  // capture-derived text and must never be parsed as markup.
  assert.doesNotThrow(() => status.recordRefusal("<img src=x onerror=alert(1)>"));
  const { refusal } = stripNodes(strip);
  assert.equal(refusal.textContent, "refused: <img src=x onerror=alert(1)>");
});

test("installStatusStrip defers mounting until the document has a body", async () => {
  const capture = await loadCapture();
  const win = makeStripWindow();
  const doc = makeStripDocument({ withBody: false });
  const status = capture.createBridgeStatus({ now: () => 1 });

  // Capture installs at document-start, so body may not exist yet.
  const strip = capture.installStatusStrip({ status, win, doc, now: () => 1 });
  assert.equal(strip.installed, true);
  assert.equal(doc.documentElement.children.length, 0, "nothing is appended while the parser is still building");

  doc.body = makeStripNode("body");
  doc.readyState = "complete";
  doc.fire("DOMContentLoaded");
  assert.equal(doc.body.children[0], strip.host);

  // The same must hold without a DOMContentLoaded listener at all: an
  // unchanged state still has to be able to mount, so render() mounts before
  // it short-circuits on an identical signature.
  const lateDoc = makeStripDocument({ withBody: false });
  delete lateDoc.addEventListener;
  const lateStrip = capture.installStatusStrip({
    status: capture.createBridgeStatus({ now: () => 1 }),
    win: makeStripWindow(),
    doc: lateDoc,
    now: () => 1,
  });
  assert.equal(lateStrip.installed, true);
  lateDoc.body = makeStripNode("body");
  lateDoc.readyState = "complete";
  lateStrip.render();
  assert.equal(lateDoc.body.children[0], lateStrip.host);
});

test("installStatusStrip refuses to install outside a top-level Fantrax league page", async () => {
  const capture = await loadCapture();
  const status = capture.createBridgeStatus({ now: () => 1 });

  assert.equal(
    capture.installStatusStrip({
      status,
      win: makeStripWindow("https://example.test/fantasy/league/abc"),
      doc: makeStripDocument(),
    }).installed,
    false
  );
  const framed = makeStripWindow();
  framed.top = {};
  assert.equal(
    capture.installStatusStrip({ status, win: framed, doc: makeStripDocument() }).installed,
    false
  );
  assert.equal(
    capture.installStatusStrip({ status, win: makeStripWindow(), doc: undefined }).installed,
    false
  );
  assert.equal(capture.installStatusStrip({ win: makeStripWindow(), doc: makeStripDocument() }).installed, false);
});

test("the menu toggle hides and restores the strip without persisting the choice", async () => {
  const capture = await loadCapture();
  const win = makeStripWindow();
  const doc = makeStripDocument();
  const status = capture.createBridgeStatus({ now: () => 1 });
  const strip = capture.installStatusStrip({ status, win, doc, now: () => 1 });

  const commands = new Map();
  assert.equal(
    capture.installStatusStripMenu({
      registerMenuCommand: (label, handler) => commands.set(label, handler),
      strip,
    }),
    true
  );
  assert.ok(commands.has("hoops-gm: show/hide status strip"));

  // The menu lives outside the page, so the strip itself never needs to
  // accept a click to be dismissable -- which is why it can keep
  // pointer-events: none.
  commands.get("hoops-gm: show/hide status strip")();
  assert.equal(strip.isVisible(), false);
  assert.equal(strip.host.style.getPropertyValue("display"), "none");

  commands.get("hoops-gm: show/hide status strip")();
  assert.equal(strip.isVisible(), true);
  assert.equal(strip.host.style.getPropertyValue("display"), "block");

  // Hiding is deliberately not written to GM storage: a remembered "hidden"
  // would recreate the silence this strip exists to break.
  const source = await readFile(new URL("../src/capture.js", import.meta.url), "utf8");
  assert.ok(!/GM_setValue/.test(source), "capture.js must not persist strip visibility");

  assert.equal(capture.installStatusStripMenu({ registerMenuCommand: () => {}, strip: null }), false);
  assert.equal(capture.installStatusStripMenu({ strip }), false);
});

test("the strip rides the rendered-view watcher's existing tick and adds no timer", async () => {
  const capture = await loadCapture();
  const clock = makeFakeClock();
  const observed = [];
  const status = {
    subscribe: () => () => {},
    snapshot: () => ({}),
    recordDelivered() {},
    recordDuplicate() {},
    recordRefusal() {},
    observeContext: (context) => observed.push(context),
  };
  const root = makeDynamicRoot(() => "view");
  const win = {
    location: { href: "https://www.fantrax.com/fantasy/league/abc/draft" },
    addEventListener: () => {},
    removeEventListener: () => {},
  };
  const doc = {
    readyState: "complete",
    visibilityState: "visible",
    documentElement: root,
    querySelector: (selector) => (selector === "main" ? root : null),
    addEventListener: () => {},
    removeEventListener: () => {},
  };
  let paired = false;
  const transport = {
    backendOrigin: "http://127.0.0.1:8000",
    isPaired: () => paired,
    sendPayload: async () => {},
  };
  const instance = capture.createCapture({ transport, now: clock.now, status });
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
    locationPollMs: 250,
    status,
  });

  assert.equal(watcher.installed, true);
  // Exactly the one pre-existing location poll. Removing the Cache Storage
  // interval and then adding a status interval would have been a wash.
  assert.equal(clock.pendingIntervals(), 1);
  // toPlain: observeContext's argument is constructed inside the vm realm, so
  // deepStrictEqual would reject it on prototype identity alone.
  assert.deepEqual(toPlain(observed), [{ paired: false }], "install seeds the strip's pairing state");

  paired = true;
  watcher.checkContext();
  assert.deepEqual(toPlain(observed[observed.length - 1]), { paired: true });
  assert.equal(clock.pendingIntervals(), 1, "no timer was added by the status path");

  watcher.uninstall();
});
