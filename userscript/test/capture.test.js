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

test("fantraxLeagueIdFromUrl returns only backend-valid external league ids", async () => {
  const capture = await loadCapture();

  for (const leagueId of [
    "b2gyornvms4606iv",
    "abc123league",
    "fantrax-league-one",
    "LG-BURN",
    "A",
    "x".repeat(64),
  ]) {
    assert.equal(
      capture.fantraxLeagueIdFromUrl(
        `https://www.fantrax.com/fantasy/league/${leagueId}/draft`
      ),
      leagueId
    );
  }

  assert.equal(
    capture.fantraxLeagueIdFromUrl(
      "https://fantrax.com/fantasy/league/fantrax-league-one?view=players"
    ),
    "fantrax-league-one"
  );

  const invalidCharacters = [
    "\u0000",
    "\u0001",
    "\u0008",
    "\t",
    "\n",
    "\u000b",
    "\u000c",
    "\r",
    "\u000e",
    "\u001c",
    "\u001d",
    "\u001e",
    "\u001f",
    "\u007f",
    "\u0085",
    "\u00a0",
    "\u1680",
    "\u2000",
    "\u2001",
    "\u2002",
    "\u2003",
    "\u2004",
    "\u2005",
    "\u2006",
    "\u2007",
    "\u2008",
    "\u2009",
    "\u200a",
    "\u200b",
    "\u2028",
    "\u2029",
    "\u202f",
    "\u205f",
    "\u3000",
    "\ufeff",
    "/",
    "?",
    "&",
    "=",
    "%",
    "_",
    "é",
  ];
  for (const character of invalidCharacters) {
    const encoded = encodeURIComponent(character);
    assert.equal(
      capture.fantraxLeagueIdFromUrl(
        `https://www.fantrax.com/fantasy/league/contains${encoded}character/draft`
      ),
      null,
      `U+${character.codePointAt(0).toString(16).toUpperCase().padStart(4, "0")} must be refused`
    );
  }

  assert.equal(
    capture.fantraxLeagueIdFromUrl("https://www.fantrax.com/fantasy/league//draft"),
    null
  );
  assert.equal(
    capture.fantraxLeagueIdFromUrl(
      `https://www.fantrax.com/fantasy/league/${"x".repeat(65)}/draft`
    ),
    null
  );
  assert.equal(
    capture.fantraxLeagueIdFromUrl("https://www.fantrax.com/fantasy/league/%E0%A4%A/draft"),
    null
  );
  assert.equal(capture.fantraxLeagueIdFromUrl("https://example.test/fantasy/league/abc"), null);
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

test("a comment terminator must fit entirely inside the snapshot content budget", async () => {
  const capture = await loadCapture();
  const maxChars = 100;
  const marker = `<!-- hoops-gm bridge: truncated at ${maxChars} chars -->`;
  const prefixBudget = maxChars - marker.length - 1;
  const opening = "<main><!--";
  const terminatorAt = prefixBudget - 2;
  const outerHTML = `${opening}${"x".repeat(terminatorAt - opening.length)}-->${"y".repeat(200)}`;
  const root = {
    cloneNode: () => ({
      outerHTML,
      querySelectorAll: () => [],
    }),
  };
  const html = capture.buildDomSnapshotHtml(
    { querySelector: (selector) => (selector === "main" ? root : null) },
    { maxChars }
  );

  assert.ok(html.length <= maxChars);
  assert.equal(
    html,
    `<main>\n${marker}`,
    "the over-budget comment end is not selected as a safe prefix boundary"
  );
});

test("generic truncation preserves safe text content up to the marker budget", async () => {
  const capture = await loadCapture();
  const text = "x".repeat(600000);
  const root = {
    cloneNode: () => ({
      outerHTML: `<main>${text}</main>`,
      querySelectorAll: () => [],
    }),
  };
  const html = capture.buildDomSnapshotHtml({
    querySelector: (selector) => (selector === "main" ? root : null),
  });

  assert.ok(html.length <= 500000);
  assert.match(html, /hoops-gm bridge: truncated at 500000 chars/);
  assert.ok(
    (html.match(/x/g) || []).length > 499000,
    "safe text consumes the available content budget instead of being discarded"
  );
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

test("an older rendered-view completion cannot clear a newer board refusal", async () => {
  const capture = await loadCapture();
  const clock = makeFakeClock();
  const status = capture.createBridgeStatus({ now: clock.now });
  let boardBody = "safe board";
  let resolveFirst;
  const board = makeDraftBoardRoot(() => [
    '<league-draft-board-table class="league-draft-board">',
    '<div class="league-draft-board__header">all seats</div>',
    `<div class="league-draft-board__body">${boardBody}</div>`,
    "</league-draft-board-table>",
  ].join(""));
  const watcher = capture.installAutomaticRenderedViewCapture({
    capture: {
      captureRenderedView: () => new Promise((resolve) => {
        resolveFirst = resolve;
      }),
    },
    transport: {
      backendOrigin: "http://127.0.0.1:8000",
      isPaired: () => true,
    },
    win: {
      location: { href: "https://www.fantrax.com/fantasy/league/abc/draft" },
      addEventListener: () => {},
      removeEventListener: () => {},
    },
    doc: {
      readyState: "complete",
      visibilityState: "visible",
      documentElement: board,
      querySelector: (selector) => (selector === ".league-draft-board" ? board : null),
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
    status,
    logger: { warn: () => {} },
  });

  clock.advance(0);
  await flushMicrotasks();
  boardBody = "x".repeat(250000);
  watcher.requestSnapshot("mutation");
  clock.advance(60000);
  await flushMicrotasks();
  assert.match(status.snapshot().lastRefusal, /no partial board was sent/);

  resolveFirst(true);
  await flushMicrotasks();
  assert.match(
    status.snapshot().lastRefusal,
    /no partial board was sent/,
    "attempt 1 cannot recover the refusal raised by attempt 2"
  );
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
  return {
    box,
    headline: box.children[0],
    detail: box.children[1],
    feed: box.children[2],
    refusal: box.children[3],
  };
}

function makeFeedStatus(overrides = {}) {
  return {
    draft_id: 17,
    as_of: "2026-09-03T14:00:00Z",
    context_unavailable: null,
    freshness: [
      {
        transport: "bridge_capture",
        last_seen_at: "2026-09-03T13:59:58Z",
        age_seconds: 2,
        instant_count: 8,
        silent: false,
        silence_threshold_seconds: 60,
        source_claimed_at: null,
        claim_skew_seconds: null,
        contact_at: "2026-09-03T13:59:59Z",
        contact_age_seconds: 1,
        contact_is_known: true,
      },
      {
        transport: "official_http",
        last_seen_at: "2026-09-03T13:59:58Z",
        age_seconds: 2,
        instant_count: 8,
        silent: false,
        silence_threshold_seconds: 60,
        source_claimed_at: null,
        claim_skew_seconds: null,
        contact_at: null,
        contact_age_seconds: null,
        contact_is_known: false,
      },
    ],
    reconciliation: null,
    observation_count: 8,
    applied_count: 7,
    pending_count: 1,
    blocked: [],
    retryable: {},
    skipped: {},
    skipped_by_participant: [],
    unattributed_skipped: {},
    last_sequence: 7,
    board_regressions: [],
    ...overrides,
  };
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
    versionStatus: "current",
    sourceVersion: "0.5.2",
    servedVersion: "0.5.2",
    versionReason: null,
    paired: true,
    forwarded: 0,
    duplicates: 0,
    lastCaptureAtMs: null,
    lastSource: null,
    lastRefusal: null,
    feedStatus: "available",
    feedLeagueId: "league-one",
    feedReport: makeFeedStatus(),
    feedReason: null,
  };
  const at = 1_000_000;

  // 1. Unpaired. Advice, never a block -- the page keeps working either way.
  const unpaired = capture.formatStatusLines({ ...base, paired: false }, { nowMs: at });
  assert.match(unpaired.headline, /NOT PAIRED/);
  assert.match(unpaired.detail, /pair from the Tampermonkey menu/);
  assert.equal(unpaired.ok, false);

  // 2. Paired but nothing captured -- a draft that has not started.
  const idle = capture.formatStatusLines(base, { nowMs: at });
  assert.match(idle.headline, /paired \u00b7 update current$/);
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

  // 4. A stale or uncheckable build. The running version alone cannot tell
  //    whether the exact bytes served by the backend agree with source.
  const stale = capture.formatStatusLines(
    {
      ...base,
      version: "0.5.2",
      versionStatus: "mismatch",
      sourceVersion: "0.5.4",
      servedVersion: "0.5.3",
      versionReason: "userscript build version mismatch",
    },
    { nowMs: at }
  );
  assert.match(stale.refusal, /UPDATE REFUSED: served v0\.5\.3 does not match source v0\.5\.4/);
  assert.equal(stale.ok, false);
  const uncheckable = capture.formatStatusLines(
    { ...base, versionStatus: "uncheckable", versionReason: "backend unreachable" },
    { nowMs: at }
  );
  assert.equal(uncheckable.refusal, "UPDATE STATUS UNCHECKABLE: backend unreachable");
  assert.equal(uncheckable.ok, false);
});

test("formatStatusLines reports counts, source and a coarse age", async () => {
  const capture = await loadCapture();
  const capturedAt = 1_000_000;
  const state = {
    version: "0.5.2",
    versionStatus: "current",
    paired: true,
    forwarded: 3,
    duplicates: 2,
    lastCaptureAtMs: capturedAt,
    lastSource: "rendered-view",
    lastRefusal: null,
    feedStatus: "available",
    feedLeagueId: "league-one",
    feedReport: makeFeedStatus(),
    feedReason: null,
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
    { version: "0.5.2", versionStatus: "current", paired: false, forwarded: 0, duplicates: 0, lastCaptureAtMs: null, lastSource: null, lastRefusal: null },
    { version: "0.5.2", versionStatus: "current", paired: true, forwarded: 0, duplicates: 0, lastCaptureAtMs: null, lastSource: null, lastRefusal: null },
    { version: "0.5.2", versionStatus: "current", paired: true, forwarded: 9, duplicates: 4, lastCaptureAtMs: 5_000, lastSource: "manual-export", lastRefusal: null },
    { version: null, versionStatus: "uncheckable", versionReason: "installed version unavailable", paired: true, forwarded: 1, duplicates: 0, lastCaptureAtMs: 5_000, lastSource: "rendered-view", lastRefusal: "backend unreachable" },
  ];

  for (const state of states) {
    const lines = capture.formatStatusLines(state, { nowMs: 60_000 });
    const rendered = `${lines.headline} ${lines.detail} ${lines.refusal || ""}`;
    assert.ok(!forbidden.test(rendered), `status text must carry no valuation vocabulary: ${rendered}`);
  }
});

test("formatStatusLines renders canonical feed counts and trust-changing states", async () => {
  const capture = await loadCapture();
  const report = makeFeedStatus({
    observation_count: 12,
    applied_count: 7,
    pending_count: 5,
    skipped: { unreadable_player_id: 2 },
    retryable: { state_version_changed: 1 },
    blocked: ["ordered_pick_out_of_turn"],
    freshness: [
      {
        transport: "bridge_capture",
        last_seen_at: "2026-09-03T13:57:00Z",
        age_seconds: 180,
        instant_count: 12,
        silent: true,
        silence_threshold_seconds: 60,
        source_claimed_at: null,
        claim_skew_seconds: null,
        contact_at: "2026-09-03T13:57:00Z",
        contact_age_seconds: 180,
        contact_is_known: true,
      },
    ],
    reconciliation: {
      independence: {
        independent: false,
        reason: "same_transport_on_both_sides",
        left_transports: ["bridge_capture"],
        right_transports: ["bridge_capture"],
        shared_artifacts: [],
        shared_transports: ["bridge_capture"],
      },
      witnessed_by_two_transports: 0,
      agreements: [],
      unwitnessed_matches: [],
      disagreements: [{}],
      only_bridge: ["Player One"],
      only_official: ["Player Two", "Player Three"],
      caveats: ["official source returned a partial view"],
    },
    board_regressions: [{}],
  });
  const lines = capture.formatStatusLines({
    version: "0.5.5",
    versionStatus: "current",
    paired: true,
    forwarded: 1,
    duplicates: 0,
    lastCaptureAtMs: 1,
    lastSource: "rendered-view",
    lastRefusal: null,
    feedStatus: "available",
    feedLeagueId: "league-one",
    feedReport: report,
  });

  assert.equal(
    lines.feed,
    "draft 17 feed \u00b7 observed 12 \u00b7 applied 7 \u00b7 pending 5 \u00b7 skipped 2 \u00b7 retryable 1"
  );
  assert.match(lines.refusal, /FEED BLOCKED: ordered_pick_out_of_turn/);
  assert.match(lines.refusal, /FEED SKIPPED: unreadable_player_id=2/);
  assert.match(lines.refusal, /FEED RETRYING: 1 state conflict still pending/);
  assert.match(lines.refusal, /FEED STALE\/SILENT: bridge_capture 180s old \(limit 60s\)/);
  assert.match(lines.refusal, /FEED RECONCILIATION: 1 disagreement, 1 bridge-only, 2 official-only/);
  assert.match(lines.refusal, /FEED UNCORROBORATED: same_transport_on_both_sides/);
  assert.match(lines.refusal, /FEED CAVEAT: official source returned a partial view/);
  assert.match(lines.refusal, /BOARD REGRESSION: 1 pick disappeared; prior state retained/);
  assert.equal(lines.ok, false);
});

test("permanent feed skips are ordered refusal details and zero skips stay healthy", async () => {
  const capture = await loadCapture();
  const healthy = {
    version: "0.5.5",
    versionStatus: "current",
    paired: true,
    forwarded: 0,
    duplicates: 0,
    lastCaptureAtMs: null,
    lastSource: null,
    lastRefusal: null,
    feedStatus: "available",
    feedLeagueId: "league-one",
  };

  for (const [reason, count] of [
    ["player_external_id_unreadable", 1],
    ["sale_without_amount", 2],
  ]) {
    const lines = capture.formatStatusLines({
      ...healthy,
      feedReport: makeFeedStatus({ skipped: { [reason]: count } }),
    });
    assert.equal(lines.ok, false);
    assert.equal(lines.refusal, `FEED SKIPPED: ${reason}=${count}`);
  }

  const multiple = capture.formatStatusLines({
    ...healthy,
    feedReport: makeFeedStatus({
      skipped: {
        sale_without_amount: 2,
        player_external_id_unreadable: 1,
        already_in_log: 3,
      },
    }),
  });
  assert.equal(
    multiple.refusal,
    "FEED SKIPPED: already_in_log=3, player_external_id_unreadable=1, sale_without_amount=2"
  );
  assert.equal(multiple.ok, false);

  const zero = capture.formatStatusLines({
    ...healthy,
    feedReport: makeFeedStatus({
      observation_count: 0,
      applied_count: 0,
      pending_count: 0,
      skipped: { player_external_id_unreadable: 0 },
    }),
  });
  assert.equal(zero.feed, "draft 17 feed \u00b7 observed 0 \u00b7 applied 0 \u00b7 pending 0 \u00b7 skipped 0");
  assert.equal(zero.refusal, null);
  assert.equal(zero.ok, true);
});

test("skipped reason text is sanitized without hiding other feed warnings", async () => {
  const capture = await loadCapture();
  const secret = "a".repeat(64);
  const lines = capture.formatStatusLines({
    version: "0.5.5",
    versionStatus: "current",
    paired: true,
    lastRefusal: null,
    feedStatus: "available",
    feedLeagueId: "league-one",
    feedReport: makeFeedStatus({
      skipped: {
        sale_without_amount: 2,
        [`player_${secret}`]: 1,
      },
      retryable: { draft_closed: 1 },
      blocked: ["draft_pick_coordinate_mismatch"],
      freshness: [
        {
          transport: "bridge_capture",
          age_seconds: 120,
          silent: true,
          silence_threshold_seconds: 60,
          contact_age_seconds: 120,
          contact_is_known: true,
        },
      ],
      board_regressions: [{}],
    }),
  });

  assert.equal(lines.ok, false);
  assert.match(lines.refusal, /FEED SKIPPED:/);
  assert.match(lines.refusal, /sale_without_amount=2/);
  assert.doesNotMatch(lines.refusal, new RegExp(secret));
  assert.match(lines.refusal, /\[redacted\]=1/);
  assert.match(lines.refusal, /FEED BLOCKED:/);
  assert.match(lines.refusal, /FEED RETRYING:/);
  assert.match(lines.refusal, /FEED STALE\/SILENT:/);
  assert.match(lines.refusal, /BOARD REGRESSION:/);
});

test("formatStatusLines makes context and identity failures distinct from zero picks", async () => {
  const capture = await loadCapture();
  const base = {
    version: "0.5.5",
    versionStatus: "current",
    paired: true,
    forwarded: 0,
    duplicates: 0,
    lastCaptureAtMs: null,
    lastSource: null,
    lastRefusal: null,
  };

  const noDraft = capture.formatStatusLines({
    ...base,
    feedStatus: "not_found",
    feedLeagueId: "league-one",
    feedReason: "draft_for_fantrax_league_not_found",
  });
  assert.equal(noDraft.feed, "feed league-one: no local draft");
  assert.match(noDraft.refusal, /^NO LOCAL DRAFT:/);

  const ambiguous = capture.formatStatusLines({
    ...base,
    feedStatus: "ambiguous",
    feedLeagueId: "league-one",
    feedReason: "draft_for_fantrax_league_ambiguous",
  });
  assert.match(ambiguous.refusal, /^AMBIGUOUS LOCAL DRAFT:/);

  const invalid = capture.formatStatusLines({
    ...base,
    feedStatus: "invalid_page_id",
    feedLeagueId: null,
  });
  assert.match(invalid.refusal, /^FEED ID UNAVAILABLE:/);

  const unavailable = capture.formatStatusLines({
    ...base,
    feedStatus: "uncheckable",
    feedLeagueId: "league-one",
    feedReason: "backend unreachable",
  });
  assert.match(unavailable.refusal, /^FEED STATUS UNCHECKABLE: backend unreachable/);

  const context = capture.formatStatusLines({
    ...base,
    feedStatus: "available",
    feedLeagueId: "league-one",
    feedReport: makeFeedStatus({
      observation_count: 0,
      applied_count: 0,
      pending_count: 0,
      context_unavailable: "draft_source_context_unavailable",
    }),
  });
  assert.match(context.feed, /observed 0/);
  assert.match(context.refusal, /FEED CONTEXT UNAVAILABLE: draft_source_context_unavailable/);
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

test("version currency stays fail-closed across current, update, and malformed reports", async () => {
  const capture = await loadCapture();
  const status = capture.createBridgeStatus({ version: "0.5.3", now: () => 1 });

  assert.equal(status.snapshot().versionStatus, "checking");
  assert.match(capture.formatStatusLines(status.snapshot()).refusal, /checking local source/);

  status.recordVersionStatus({
    status: "update_available",
    installed_version: "0.5.3",
    source_version: "0.5.4",
    served_version: "0.5.4",
    reason: "installed_version_behind",
  });
  assert.equal(status.snapshot().versionStatus, "update_available");
  assert.match(capture.formatStatusLines(status.snapshot()).refusal, /UPDATE AVAILABLE/);

  status.recordFeedStatus(makeFeedStatus(), "league-one");
  assert.equal(
    status.snapshot().versionStatus,
    "update_available",
    "feed success cannot clear update currency"
  );
  assert.match(capture.formatStatusLines(status.snapshot()).refusal, /UPDATE AVAILABLE/);

  status.recordVersionStatus({
    status: "current",
    installed_version: "0.5.3",
    source_version: "0.5.3",
    served_version: "0.5.3",
    reason: null,
  });
  assert.equal(status.snapshot().versionStatus, "current");
  assert.equal(capture.formatStatusLines(status.snapshot()).refusal, null);

  status.recordVersionStatus({
    status: "current",
    installed_version: "0.5.3",
    source_version: "0.5.4",
    served_version: "0.5.4",
    reason: null,
  });
  assert.equal(status.snapshot().versionStatus, "uncheckable");
  assert.match(capture.formatStatusLines(status.snapshot()).refusal, /invalid local version status/);
});

test("a long-lived visible tab revalidates currency on the existing watcher tick", async () => {
  const capture = await loadCapture();
  const clock = makeFakeClock();
  const status = capture.createBridgeStatus({ version: "0.5.3", now: clock.now });
  let sourceVersion = "0.5.3";
  let calls = 0;
  const transport = {
    backendOrigin: "http://127.0.0.1:8000",
    isPaired: () => true,
    userscriptStatus: async (installedVersion) => {
      calls += 1;
      return {
        status: sourceVersion === installedVersion ? "current" : "update_available",
        installed_version: installedVersion,
        source_version: sourceVersion,
        served_version: sourceVersion,
        reason: sourceVersion === installedVersion ? null : "installed_version_behind",
      };
    },
  };
  const revalidator = capture.createVersionStatusRevalidator({
    transport,
    status,
    installedVersion: "0.5.3",
    now: clock.now,
    minIntervalMs: 1000,
  });
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
  const watcher = capture.installAutomaticRenderedViewCapture({
    capture: { captureRenderedView: async () => true },
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
    onRelevantContext: revalidator.recheck,
  });

  await flushMicrotasks();
  assert.equal(status.snapshot().versionStatus, "current");
  assert.equal(calls, 1);
  assert.equal(clock.pendingIntervals(), 1, "revalidation adds no recurring timer");

  sourceVersion = "0.5.4";
  clock.advance(999);
  watcher.checkContext();
  await flushMicrotasks();
  assert.equal(calls, 1, "the watcher tick cannot exceed the currency request bound");
  assert.equal(status.snapshot().versionStatus, "current");

  clock.advance(1);
  watcher.checkContext();
  assert.equal(status.snapshot().versionStatus, "checking", "expired currency is not shown as current");
  await flushMicrotasks();
  assert.equal(calls, 2);
  assert.equal(status.snapshot().versionStatus, "update_available");
  assert.match(capture.formatStatusLines(status.snapshot()).refusal, /UPDATE AVAILABLE/);

  watcher.uninstall();
  revalidator.stop();
});

test("a failed currency recheck replaces prior current state with uncheckable", async () => {
  const capture = await loadCapture();
  const clock = makeFakeClock();
  const status = capture.createBridgeStatus({ version: "0.5.3", now: clock.now });
  let fail = false;
  const revalidator = capture.createVersionStatusRevalidator({
    transport: {
      userscriptStatus: async (installedVersion) => {
        if (fail) {
          throw new Error("backend request timed out");
        }
        return {
          status: "current",
          installed_version: installedVersion,
          source_version: installedVersion,
          served_version: installedVersion,
          reason: null,
        };
      },
    },
    status,
    installedVersion: "0.5.3",
    now: clock.now,
    minIntervalMs: 1000,
  });

  revalidator.recheck();
  await flushMicrotasks();
  assert.equal(status.snapshot().versionStatus, "current");

  fail = true;
  clock.advance(1000);
  revalidator.recheck();
  assert.equal(status.snapshot().versionStatus, "checking");
  await flushMicrotasks();
  assert.equal(status.snapshot().versionStatus, "uncheckable");
  assert.match(capture.formatStatusLines(status.snapshot()).refusal, /request timed out/);

  status.recordDelivered("rendered-view");
  assert.equal(
    status.snapshot().versionStatus,
    "uncheckable",
    "capture success cannot clear update currency"
  );
});

test("an older deferred currency response cannot overwrite a newer result", async () => {
  const capture = await loadCapture();
  const clock = makeFakeClock();
  const status = capture.createBridgeStatus({ version: "0.5.3", now: clock.now });
  const pending = [];
  const revalidator = capture.createVersionStatusRevalidator({
    transport: {
      userscriptStatus: () => new Promise((resolve) => pending.push(resolve)),
    },
    status,
    installedVersion: "0.5.3",
    now: clock.now,
    minIntervalMs: 1000,
  });

  revalidator.recheck();
  await flushMicrotasks();
  clock.advance(1000);
  revalidator.recheck();
  await flushMicrotasks();
  assert.equal(pending.length, 2);

  pending[1]({
    status: "update_available",
    installed_version: "0.5.3",
    source_version: "0.5.4",
    served_version: "0.5.4",
    reason: "installed_version_behind",
  });
  await flushMicrotasks();
  assert.equal(status.snapshot().versionStatus, "update_available");

  pending[0]({
    status: "current",
    installed_version: "0.5.3",
    source_version: "0.5.3",
    served_version: "0.5.3",
    reason: null,
  });
  await flushMicrotasks();
  assert.equal(
    status.snapshot().versionStatus,
    "update_available",
    "only the latest request generation may publish"
  );
  assert.equal(status.snapshot().sourceVersion, "0.5.4");
});

test("feed revalidation uses the page league id, clears stale counts, and stays bounded", async () => {
  const capture = await loadCapture();
  const clock = makeFakeClock();
  const status = capture.createBridgeStatus({ version: "0.5.5", now: clock.now });
  const reports = [
    makeFeedStatus({ observation_count: 3, applied_count: 3, pending_count: 0 }),
    makeFeedStatus({ observation_count: 4, applied_count: 3, pending_count: 1 }),
  ];
  const requested = [];
  const revalidator = capture.createFeedStatusRevalidator({
    transport: {
      draftFeedStatus: async (leagueId) => {
        requested.push(leagueId);
        return reports.shift();
      },
    },
    status,
    now: clock.now,
    minIntervalMs: 1000,
  });

  assert.equal(
    revalidator.recheck("https://www.fantrax.com/fantasy/league/league-one/draft"),
    true
  );
  assert.equal(status.snapshot().feedStatus, "checking");
  assert.equal(status.snapshot().feedReport, null);
  await flushMicrotasks();
  assert.equal(status.snapshot().feedStatus, "available");
  assert.equal(status.snapshot().feedReport.observation_count, 3);
  assert.deepEqual(requested, ["league-one"]);

  clock.advance(999);
  assert.equal(
    revalidator.recheck("https://www.fantrax.com/fantasy/league/league-one/draft"),
    false
  );
  assert.equal(status.snapshot().feedReport.observation_count, 3);

  clock.advance(1);
  assert.equal(
    revalidator.recheck("https://www.fantrax.com/fantasy/league/league-one/draft"),
    true
  );
  assert.equal(status.snapshot().feedStatus, "checking");
  assert.equal(
    status.snapshot().feedReport,
    null,
    "an expired refresh cannot retain a previous green count"
  );
  await flushMicrotasks();
  assert.equal(status.snapshot().feedReport.observation_count, 4);
  assert.deepEqual(requested, ["league-one", "league-one"]);
});

test("feed revalidation names zero-match, ambiguity, invalid page id, and network failures", async () => {
  const capture = await loadCapture();
  const clock = makeFakeClock();
  const status = capture.createBridgeStatus({ version: "0.5.5", now: clock.now });
  const failures = [
    Object.assign(new Error("backend returned HTTP 404"), {
      code: "draft_for_fantrax_league_not_found",
    }),
    Object.assign(new Error("backend returned HTTP 409"), {
      code: "draft_for_fantrax_league_ambiguous",
    }),
    new Error("backend unreachable"),
  ];
  let calls = 0;
  const revalidator = capture.createFeedStatusRevalidator({
    transport: {
      draftFeedStatus: async () => {
        calls += 1;
        throw failures.shift();
      },
    },
    status,
    now: clock.now,
    minIntervalMs: 1000,
  });
  const url = "https://www.fantrax.com/fantasy/league/league-one/draft";

  revalidator.recheck(url);
  await flushMicrotasks();
  assert.equal(status.snapshot().feedStatus, "not_found");
  assert.match(capture.formatStatusLines(status.snapshot()).refusal, /NO LOCAL DRAFT/);

  clock.advance(1000);
  revalidator.recheck(url);
  await flushMicrotasks();
  assert.equal(status.snapshot().feedStatus, "ambiguous");
  assert.match(capture.formatStatusLines(status.snapshot()).refusal, /AMBIGUOUS LOCAL DRAFT/);

  clock.advance(1000);
  revalidator.recheck(url);
  await flushMicrotasks();
  assert.equal(status.snapshot().feedStatus, "uncheckable");
  assert.equal(status.snapshot().feedReport, null);
  assert.match(capture.formatStatusLines(status.snapshot()).refusal, /backend unreachable/);

  assert.equal(
    revalidator.recheck(
      "https://www.fantrax.com/fantasy/league/contains%20whitespace/draft"
    ),
    false
  );
  assert.equal(status.snapshot().feedStatus, "invalid_page_id");
  assert.equal(status.snapshot().feedReport, null);
  assert.equal(calls, 3, "a malformed or absent page id must never reach the backend");

  assert.equal(
    revalidator.recheck("https://www.fantrax.com/fantasy/home"),
    false
  );
  assert.equal(status.snapshot().feedStatus, "invalid_page_id");
  assert.equal(calls, 3, "a page without a league id must never reach the backend");
});

test("feed revalidation rejects malformed success and capture or update changes cannot erase it", async () => {
  const capture = await loadCapture();
  const status = capture.createBridgeStatus({ version: "0.5.5", now: () => 1 });
  const revalidator = capture.createFeedStatusRevalidator({
    transport: { draftFeedStatus: async () => ({ draft_id: 17 }) },
    status,
  });

  revalidator.recheck("https://www.fantrax.com/fantasy/league/league-one/draft");
  await flushMicrotasks();
  assert.equal(status.snapshot().feedStatus, "uncheckable");
  assert.match(
    capture.formatStatusLines(status.snapshot()).refusal,
    /invalid local feed status response/
  );

  status.recordDelivered("rendered-view");
  status.recordVersionStatus({
    status: "current",
    installed_version: "0.5.5",
    source_version: "0.5.5",
    served_version: "0.5.5",
    reason: null,
  });
  assert.equal(status.snapshot().feedStatus, "uncheckable");
  assert.match(
    capture.formatStatusLines(status.snapshot()).refusal,
    /invalid local feed status response/
  );
});

test("feed refresh rejects a participant skip omitted from the aggregate", async () => {
  const capture = await loadCapture();
  const url = "https://www.fantrax.com/fantasy/league/league-one/draft";
  const malformed = makeFeedStatus({
    skipped: {},
    skipped_by_participant: [
      {
        participant_id: 101,
        team_slot: 1,
        total: 1,
        reasons: { player_external_id_unreadable: 1 },
      },
    ],
    unattributed_skipped: {},
  });
  const status = capture.createBridgeStatus({ version: "0.5.5", now: () => 1 });
  status.recordFeedStatus(makeFeedStatus(), "league-one");
  assert.equal(status.snapshot().feedStatus, "available");

  const revalidator = capture.createFeedStatusRevalidator({
    transport: { draftFeedStatus: async () => malformed },
    status,
    readCurrentUrl: () => url,
  });
  revalidator.recheck(url);
  assert.equal(status.snapshot().feedReport, null, "refresh start clears prior green evidence");
  await flushMicrotasks();

  const snapshot = status.snapshot();
  const lines = capture.formatStatusLines({
    ...snapshot,
    paired: true,
    versionStatus: "current",
  });
  assert.equal(snapshot.feedStatus, "uncheckable");
  assert.equal(snapshot.feedReport, null);
  assert.match(lines.feed, /status uncheckable/);
  assert.match(lines.refusal, /FEED STATUS UNCHECKABLE: invalid local feed status response/);
  assert.doesNotMatch(lines.feed, /skipped 0/);
  assert.equal(lines.ok, false);
});

test("feed refresh rejects malformed freshness instead of publishing a false green", async () => {
  const capture = await loadCapture();
  const url = "https://www.fantrax.com/fantasy/league/league-one/draft";
  const malformed = makeFeedStatus({
    freshness: [
      {
        transport: "bridge_capture",
        silent: false,
        silence_threshold_seconds: -1,
        instant_count: 0,
      },
    ],
  });
  const status = capture.createBridgeStatus({ version: "0.5.5", now: () => 1 });
  status.recordFeedStatus(makeFeedStatus(), "league-one");

  const revalidator = capture.createFeedStatusRevalidator({
    transport: { draftFeedStatus: async () => malformed },
    status,
    readCurrentUrl: () => url,
  });
  revalidator.recheck(url);
  await flushMicrotasks();

  const snapshot = status.snapshot();
  const lines = capture.formatStatusLines({
    ...snapshot,
    paired: true,
    versionStatus: "current",
  });
  assert.equal(snapshot.feedStatus, "uncheckable");
  assert.equal(snapshot.feedReport, null);
  assert.match(lines.refusal, /FEED STATUS UNCHECKABLE: invalid local feed status response/);
  assert.equal(lines.ok, false);
});

test("feed validation enforces the complete freshness contract and clock relationships", async () => {
  const capture = await loadCapture();
  const [valid, official] = makeFeedStatus().freshness;
  const invalidFreshness = [
    ["empty source list", []],
    ["missing source", [valid]],
    ["duplicate source", [valid, { ...valid }]],
    ["extra field", [{ ...valid, unexpected: true }, official]],
    ["unknown transport", [{ ...valid, transport: "browser_guess" }, official]],
    ["negative age", [{ ...valid, age_seconds: -1 }, official]],
    ["fractional instant count", [{ ...valid, instant_count: 1.5 }, official]],
    ["last-seen pair mismatch", [{ ...valid, age_seconds: null }, official]],
    ["claim pair mismatch", [{ ...valid, claim_skew_seconds: 0 }, official]],
    ["contact pair mismatch", [{ ...valid, contact_age_seconds: null }, official]],
    ["contact flag mismatch", [{ ...valid, contact_is_known: false }, official]],
    [
      "silent decision mismatch",
      [
        {
          ...valid,
          age_seconds: 120,
          contact_is_known: false,
          contact_at: null,
          contact_age_seconds: null,
        },
        official,
      ],
    ],
    [
      "zero instants cannot be healthy",
      [
        {
          ...valid,
          last_seen_at: null,
          age_seconds: null,
          instant_count: 0,
          source_claimed_at: null,
          claim_skew_seconds: null,
          silent: false,
        },
        official,
      ],
    ],
  ];

  for (const [name, freshness] of invalidFreshness) {
    const status = capture.createBridgeStatus({ version: "0.5.5", now: () => 1 });
    status.recordFeedStatus(makeFeedStatus({ freshness }), "league-one");
    assert.equal(status.snapshot().feedStatus, "uncheckable", name);
    assert.equal(status.snapshot().feedReport, null, name);
  }
});

test("feed validation rejects every malformed or unreconciled permanent-skip partition", async () => {
  const capture = await loadCapture();
  const participant = (overrides = {}) => ({
    participant_id: 101,
    team_slot: 1,
    total: 1,
    reasons: { player_external_id_unreadable: 1 },
    ...overrides,
  });
  const invalidReports = [
    [
      "extra aggregate reason",
      makeFeedStatus({
        skipped: { player_external_id_unreadable: 1, sale_without_amount: 1 },
        skipped_by_participant: [participant()],
      }),
    ],
    [
      "zero-count aggregate reason missing from partition",
      makeFeedStatus({ skipped: { player_external_id_unreadable: 0 } }),
    ],
    [
      "extra partition reason",
      makeFeedStatus({
        skipped: { player_external_id_unreadable: 1 },
        skipped_by_participant: [participant()],
        unattributed_skipped: { sale_without_amount: 1 },
      }),
    ],
    [
      "zero-count partition reason missing from aggregate",
      makeFeedStatus({ unattributed_skipped: { player_external_id_unreadable: 0 } }),
    ],
    [
      "participant total mismatch",
      makeFeedStatus({
        skipped: { player_external_id_unreadable: 1 },
        skipped_by_participant: [participant({ total: 2 })],
      }),
    ],
    ["negative aggregate count", makeFeedStatus({ skipped: { invalid: -1 } })],
    [
      "fractional participant count",
      makeFeedStatus({
        skipped: { invalid: 1.5 },
        skipped_by_participant: [
          participant({ total: 1.5, reasons: { invalid: 1.5 } }),
        ],
      }),
    ],
    [
      "string unattributed count",
      makeFeedStatus({
        skipped: { invalid: 1 },
        unattributed_skipped: { invalid: "1" },
      }),
    ],
    ["aggregate array", makeFeedStatus({ skipped: [] })],
    ["unattributed array", makeFeedStatus({ unattributed_skipped: [] })],
    ["malformed participant", makeFeedStatus({ skipped_by_participant: [null] })],
    [
      "participant reason array",
      makeFeedStatus({
        skipped_by_participant: [participant({ total: 0, reasons: [] })],
      }),
    ],
    [
      "participant with extra field",
      makeFeedStatus({
        skipped_by_participant: [participant({ unexpected: true })],
      }),
    ],
    [
      "invalid participant identifier",
      makeFeedStatus({
        skipped_by_participant: [
          participant({ participant_id: "101", total: 0, reasons: {} }),
        ],
      }),
    ],
    [
      "invalid participant slot",
      makeFeedStatus({
        skipped_by_participant: [participant({ team_slot: 0, total: 0, reasons: {} })],
      }),
    ],
  ];

  for (const [name, report] of invalidReports) {
    const status = capture.createBridgeStatus({ version: "0.5.5", now: () => 1 });
    status.recordFeedStatus(makeFeedStatus(), "league-one");
    assert.equal(status.snapshot().feedStatus, "available", `${name}: valid baseline`);

    status.recordFeedStatus(report, "league-one");
    const snapshot = status.snapshot();
    const lines = capture.formatStatusLines({
      ...snapshot,
      paired: true,
      versionStatus: "current",
    });
    assert.equal(snapshot.feedStatus, "uncheckable", name);
    assert.equal(snapshot.feedReport, null, `${name}: prior count evidence must clear`);
    assert.match(lines.feed, /status uncheckable/, name);
    assert.match(lines.refusal, /FEED STATUS UNCHECKABLE: invalid local feed status response/, name);
    assert.doesNotMatch(lines.feed, /skipped 0/, `${name}: malformed aggregate is not salvaged`);
    assert.equal(lines.ok, false, name);
  }
});

test("feed validation accepts only reconciled participant and unattributed skip partitions", async () => {
  const capture = await loadCapture();
  const status = capture.createBridgeStatus({ version: "0.5.5", now: () => 1 });
  const linesAfter = (report) => {
    status.recordFeedStatus(report, "league-one");
    return capture.formatStatusLines({
      ...status.snapshot(),
      paired: true,
      versionStatus: "current",
    });
  };

  const unattributed = linesAfter(
    makeFeedStatus({
      skipped: { source_board_evidence_only: 2 },
      skipped_by_participant: [],
      unattributed_skipped: { source_board_evidence_only: 2 },
    })
  );
  assert.equal(status.snapshot().feedStatus, "available");
  assert.equal(unattributed.refusal, "FEED SKIPPED: source_board_evidence_only=2");
  assert.equal(unattributed.ok, false);

  const partitioned = linesAfter(
    makeFeedStatus({
      skipped: {
        already_in_log: 3,
        player_external_id_unreadable: 3,
        source_board_evidence_only: 4,
      },
      skipped_by_participant: [
        {
          participant_id: 101,
          team_slot: 1,
          total: 3,
          reasons: {
            already_in_log: 2,
            player_external_id_unreadable: 1,
          },
        },
        {
          participant_id: 102,
          team_slot: 2,
          total: 3,
          reasons: {
            already_in_log: 1,
            player_external_id_unreadable: 2,
          },
        },
      ],
      unattributed_skipped: { source_board_evidence_only: 4 },
    })
  );
  assert.equal(status.snapshot().feedStatus, "available");
  assert.equal(
    partitioned.refusal,
    "FEED SKIPPED: already_in_log=3, player_external_id_unreadable=3, source_board_evidence_only=4"
  );
  assert.equal(partitioned.ok, false);

  const zero = linesAfter(
    makeFeedStatus({
      skipped: {},
      skipped_by_participant: [
        { participant_id: 101, team_slot: 1, total: 0, reasons: {} },
        { participant_id: 102, team_slot: 2, total: 0, reasons: {} },
      ],
      unattributed_skipped: {},
    })
  );
  assert.equal(status.snapshot().feedStatus, "available");
  assert.equal(zero.refusal, null);
  assert.equal(zero.ok, true);
});

test("a league navigation invalidates an older in-flight feed response", async () => {
  const capture = await loadCapture();
  const clock = makeFakeClock();
  const status = capture.createBridgeStatus({ version: "0.5.5", now: clock.now });
  const pending = [];
  const requested = [];
  const revalidator = capture.createFeedStatusRevalidator({
    transport: {
      draftFeedStatus: (leagueId) => {
        requested.push(leagueId);
        return new Promise((resolve) => pending.push(resolve));
      },
    },
    status,
    now: clock.now,
    minIntervalMs: 60000,
  });

  revalidator.recheck("https://www.fantrax.com/fantasy/league/league-one/draft");
  await flushMicrotasks();
  revalidator.recheck("https://www.fantrax.com/fantasy/league/league-two/draft");
  await flushMicrotasks();
  assert.deepEqual(requested, ["league-one", "league-two"]);
  assert.equal(
    status.snapshot().feedLeagueId,
    "league-two",
    "a league change bypasses the same-league cadence bound"
  );

  pending[1](makeFeedStatus({ draft_id: 22, observation_count: 2 }));
  await flushMicrotasks();
  assert.equal(status.snapshot().feedReport.draft_id, 22);
  pending[0](makeFeedStatus({ draft_id: 11, observation_count: 99 }));
  await flushMicrotasks();
  assert.equal(status.snapshot().feedReport.draft_id, 22);
  assert.equal(status.snapshot().feedReport.observation_count, 2);
});

test("feed completion rechecks live page identity before the watcher observes navigation", async () => {
  const capture = await loadCapture();
  const page = {
    url: "https://www.fantrax.com/fantasy/league/league-one/draft",
  };

  for (const outcome of ["success", "failure"]) {
    const status = capture.createBridgeStatus({ version: "0.5.5", now: () => 1 });
    let settle;
    const revalidator = capture.createFeedStatusRevalidator({
      transport: {
        draftFeedStatus: () =>
          new Promise((resolve, reject) => {
            settle = outcome === "success" ? resolve : reject;
          }),
      },
      status,
      readCurrentUrl: () => page.url,
    });

    page.url = "https://www.fantrax.com/fantasy/league/league-one/draft";
    revalidator.recheck(page.url);
    await flushMicrotasks();
    assert.equal(status.snapshot().feedStatus, "checking");

    page.url = "https://www.fantrax.com/fantasy/league/league-two/draft";
    settle(
      outcome === "success"
        ? makeFeedStatus({ draft_id: 11, observation_count: 99 })
        : new Error("league-one request failed")
    );
    await flushMicrotasks();

    assert.equal(
      status.snapshot().feedStatus,
      "checking",
      `a stale ${outcome} must not publish before the watcher observes league-two`
    );
    assert.equal(status.snapshot().feedReport, null);
    assert.equal(status.snapshot().feedReason, null);
    revalidator.stop();
  }
});

test("a long-lived visible tab refreshes feed status on the existing watcher only", async () => {
  const capture = await loadCapture();
  const clock = makeFakeClock();
  const status = capture.createBridgeStatus({ version: "0.5.5", now: clock.now });
  let observationCount = 1;
  let calls = 0;
  const transport = {
    backendOrigin: "http://127.0.0.1:8000",
    isPaired: () => true,
    sendPayload: async () => {},
    draftFeedStatus: async () => {
      calls += 1;
      return makeFeedStatus({ observation_count: observationCount });
    },
  };
  const revalidator = capture.createFeedStatusRevalidator({
    transport,
    status,
    now: clock.now,
    minIntervalMs: 1000,
  });
  const root = makeDynamicRoot(() => "view");
  const win = {
    location: { href: "https://www.fantrax.com/fantasy/league/league-one/draft" },
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
  const watcher = capture.installAutomaticRenderedViewCapture({
    capture: { captureRenderedView: async () => true },
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
    onRelevantContext: revalidator.recheck,
  });

  await flushMicrotasks();
  assert.equal(calls, 1);
  assert.equal(status.snapshot().feedReport.observation_count, 1);
  assert.equal(clock.pendingIntervals(), 1);

  observationCount = 2;
  clock.advance(999);
  watcher.checkContext();
  await flushMicrotasks();
  assert.equal(calls, 1);
  clock.advance(1);
  watcher.checkContext();
  assert.equal(status.snapshot().feedStatus, "checking");
  await flushMicrotasks();
  assert.equal(calls, 2);
  assert.equal(status.snapshot().feedReport.observation_count, 2);
  assert.equal(clock.pendingIntervals(), 1, "feed status adds no recurring timer");

  watcher.uninstall();
  revalidator.stop();
});

test("the existing watcher clears feed evidence and invalidates an in-flight response after leaving a league", async () => {
  const capture = await loadCapture();
  const clock = makeFakeClock();
  const status = capture.createBridgeStatus({ version: "0.5.5", now: clock.now });
  let resolveFeed;
  const transport = {
    backendOrigin: "http://127.0.0.1:8000",
    isPaired: () => true,
    sendPayload: async () => {},
    draftFeedStatus: () =>
      new Promise((resolve) => {
        resolveFeed = resolve;
      }),
  };
  const revalidator = capture.createFeedStatusRevalidator({
    transport,
    status,
    now: clock.now,
    minIntervalMs: 1000,
  });
  const root = makeDynamicRoot(() => "view");
  const win = {
    location: { href: "https://www.fantrax.com/fantasy/league/league-one/draft" },
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
  const watcher = capture.installAutomaticRenderedViewCapture({
    capture: { captureRenderedView: async () => true },
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
    onRelevantContext: revalidator.recheck,
  });

  await flushMicrotasks();
  assert.equal(status.snapshot().feedStatus, "checking");

  win.location.href = "https://www.fantrax.com/fantasy/home";
  watcher.checkContext();
  assert.equal(status.snapshot().feedStatus, "invalid_page_id");
  assert.equal(status.snapshot().feedReport, null);

  resolveFeed(makeFeedStatus({ draft_id: 11, observation_count: 99 }));
  await flushMicrotasks();
  assert.equal(status.snapshot().feedStatus, "invalid_page_id");
  assert.equal(status.snapshot().feedReport, null);

  watcher.uninstall();
  revalidator.stop();
});

test("an unrelated success cannot clear an automatic board refusal", async () => {
  const capture = await loadCapture();
  const status = capture.createBridgeStatus({ now: () => 1 });

  status.recordRefusal("draft board snapshot exceeds cap", "rendered-view", 2);
  status.recordRefusal("backend temporarily unavailable");
  assert.equal(status.snapshot().lastRefusal, "backend temporarily unavailable");

  status.recordDelivered("manual-export");
  assert.equal(status.snapshot().lastRefusal, "draft board snapshot exceeds cap");
  assert.equal(status.snapshot().lastRefusalSource, "rendered-view");

  status.recordDuplicate("rendered-view");
  assert.equal(
    status.snapshot().lastRefusal,
    "draft board snapshot exceeds cap",
    "generic same-source delivery state is not correlated to the board attempt"
  );
  status.recordRecovery("rendered-view", 1);
  assert.equal(
    status.snapshot().lastRefusal,
    "draft board snapshot exceeds cap",
    "an older in-flight attempt cannot clear a newer refusal"
  );
  status.recordRecovery("rendered-view", 3);
  assert.equal(status.snapshot().lastRefusal, null);
  assert.equal(status.snapshot().lastRefusalSource, null);
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

  const { box, headline, detail, feed, refusal } = stripNodes(strip);
  assert.match(headline.textContent, /hoops-gm v0\.5\.2 \u00b7 NOT PAIRED/);
  assert.match(detail.textContent, /pair from the Tampermonkey menu/);
  assert.equal(box.style.getPropertyValue("white-space"), "normal");
  assert.equal(box.style.getPropertyValue("overflow"), "visible");
  assert.equal(box.style.getPropertyValue("overflow-wrap"), "anywhere");
  for (const singleLine of [headline, detail, feed]) {
    assert.equal(singleLine.style.getPropertyValue("white-space"), "nowrap");
    assert.equal(singleLine.style.getPropertyValue("overflow"), "hidden");
    assert.equal(singleLine.style.getPropertyValue("text-overflow"), "ellipsis");
  }
  assert.equal(refusal.style.getPropertyValue("white-space"), "normal");
  assert.equal(refusal.style.getPropertyValue("overflow-wrap"), "anywhere");
});

test("the status strip re-renders on real transitions and stays silent otherwise", async () => {
  const capture = await loadCapture();
  const win = makeStripWindow();
  const doc = makeStripDocument();
  let clock = 1_000;
  const status = capture.createBridgeStatus({ version: "0.5.2", now: () => clock });
  status.recordVersionStatus({
    status: "current",
    installed_version: "0.5.2",
    source_version: "0.5.2",
    served_version: "0.5.2",
    reason: null,
  });
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
  assert.match(headline.textContent, /\u00b7 paired \u00b7 update current$/);
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
  status.recordVersionStatus({
    status: "current",
    installed_version: "0.5.2",
    source_version: "0.5.2",
    served_version: "0.5.2",
    reason: null,
  });
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
