(() => {
  "use strict";

  // Strictly read-only capture of Fantrax's internal /fxpa/req JSON-RPC
  // endpoint. This module never modifies a request or a response, never
  // blocks the page from receiving its real fetch/XHR result, and never
  // throws into page code: every capture path is wrapped so a bug here can
  // at most silently drop one capture, never break Fantrax's own UI.
  //
  // It captures RESPONSES only. Outgoing request bodies and all headers
  // (cookie, auth, or otherwise) are never read or forwarded -- only the
  // method, URL, response status/ok, response Content-Type, and response
  // body are captured. See ADR-004: /fxpa/req is undocumented internal
  // infrastructure and is read here, never written to.

  const ENVELOPE_SCHEMA = "hoops-gm.bridge-payload.v1";
  const FXPA_REQ_PATHNAME = "/fxpa/req";
  const FANTRAX_HOSTS = new Set(["fantrax.com", "www.fantrax.com"]);
  // Fixed, not derived from window.location: capture is only ever installed
  // on pages matching the userscript's own narrow @match rule, and a fixed
  // base keeps filtering deterministic and testable outside a browser.
  const CAPTURE_BASE = "https://www.fantrax.com";

  /**
   * @typedef {Object} BridgePayloadEnvelope
   * @property {string} schema
   * @property {"fetch"|"xhr"} source
   * @property {string} capturedAt ISO-8601 timestamp
   * @property {{method: string, url: string}} request
   * @property {{status: number|null, ok: boolean, contentType: string|null}} response
   * @property {{raw: string, json: unknown|null, parseError: string|null}} body
   * @property {string} dedupeKey
   */

  /**
   * True only for the exact Fantrax internal RPC endpoint this bridge is
   * scoped to. Deliberately an exact pathname match (no prefix matching)
   * so the capture surface cannot silently widen if Fantrax adds a
   * similarly named but unrelated path.
   */
  function shouldCapture(url) {
    if (typeof url !== "string" || url.length === 0) {
      return false;
    }
    let parsed;
    try {
      parsed = new URL(url, CAPTURE_BASE);
    } catch {
      return false;
    }
    return FANTRAX_HOSTS.has(parsed.hostname.toLowerCase()) && parsed.pathname === FXPA_REQ_PATHNAME;
  }

  /** 32-bit FNV-1a. Not cryptographic -- only used to collapse duplicate captures. */
  function fnv1a(input) {
    let hash = 0x811c9dc5;
    for (let i = 0; i < input.length; i += 1) {
      hash ^= input.charCodeAt(i);
      hash = Math.imul(hash, 0x01000193);
    }
    return (hash >>> 0).toString(16).padStart(8, "0");
  }

  function computeDedupeKey(method, url, raw) {
    const safeMethod = (method || "GET").toUpperCase();
    return `${safeMethod}:${fnv1a(url || "")}:${fnv1a(raw || "")}`;
  }

  /**
   * Never throws: a malformed or non-JSON response body (an HTML error page,
   * a truncated response, an empty body) is preserved raw with the parse
   * failure recorded, rather than dropped or thrown.
   */
  function normalizeBody(raw) {
    const text = typeof raw === "string" ? raw : "";
    if (text.length === 0) {
      return { raw: text, json: null, parseError: "empty response body" };
    }
    try {
      return { raw: text, json: JSON.parse(text), parseError: null };
    } catch (err) {
      return {
        raw: text,
        json: null,
        parseError: err instanceof Error ? err.message : "invalid JSON",
      };
    }
  }

  /** @returns {BridgePayloadEnvelope} */
  function buildEnvelope({ source, url, method, status, ok, contentType, raw, capturedAtMs }) {
    const body = normalizeBody(raw);
    return {
      schema: ENVELOPE_SCHEMA,
      source,
      capturedAt: new Date(capturedAtMs).toISOString(),
      request: {
        method: (method || "GET").toUpperCase(),
        url,
      },
      response: {
        status: typeof status === "number" ? status : null,
        ok: Boolean(ok),
        contentType: contentType || null,
      },
      body,
      dedupeKey: computeDedupeKey(method, url, body.raw),
    };
  }

  /**
   * Small bounded recency cache so a page polling the same RPC call every
   * few seconds does not forward byte-identical payloads on every tick.
   * FIFO eviction keeps memory bounded across a multi-hour draft session.
   */
  function createDedupeCache({ maxEntries = 200 } = {}) {
    const seenKeys = new Map();
    return {
      seen(key) {
        if (seenKeys.has(key)) {
          seenKeys.delete(key);
          seenKeys.set(key, true);
          return true;
        }
        seenKeys.set(key, true);
        if (seenKeys.size > maxEntries) {
          const oldest = seenKeys.keys().next().value;
          seenKeys.delete(oldest);
        }
        return false;
      },
      size() {
        return seenKeys.size;
      },
      clear() {
        seenKeys.clear();
      },
    };
  }

  function safeWarn(logger, message) {
    try {
      logger.warn(message);
    } catch {
      // A broken logger must never propagate into the page.
    }
  }

  /**
   * Wires filtering, normalization, dedupe and forwarding together.
   * Dependency-injected so it is testable without a browser: `transport`
   * is anything shaped like `HoopsGmTransport` (an object with
   * `sendPayload`), `now` and `dedupe` are overridable for deterministic
   * tests, and `installFetch`/`installXHR` take an explicit `win` object
   * rather than reading the global directly.
   */
  function createCapture({
    transport,
    now = () => Date.now(),
    dedupe = createDedupeCache(),
    logger = console,
  } = {}) {
    function forward(envelope) {
      if (!transport || typeof transport.sendPayload !== "function") {
        return;
      }
      if (dedupe.seen(envelope.dedupeKey)) {
        return;
      }
      // Fire-and-forget: forwarding must never delay or block the response
      // the page itself is waiting on, and a rejected forward must never
      // become an unhandled rejection.
      Promise.resolve()
        .then(() => transport.sendPayload(envelope))
        .catch(() => {
          safeWarn(
            logger,
            `hoops-gm bridge: failed to forward captured payload (${envelope.request.method} ${envelope.request.url})`
          );
        });
    }

    function handleCaptured(details) {
      try {
        if (!shouldCapture(details.url)) {
          return;
        }
        const envelope = buildEnvelope({ ...details, capturedAtMs: now() });
        forward(envelope);
      } catch (err) {
        safeWarn(logger, `hoops-gm bridge: capture failed (${err && err.message})`);
      }
    }

    function installFetch(win) {
      return installFetchCapture({ win, handleCaptured, logger });
    }

    function installXHR(win) {
      return installXHRCapture({ win, handleCaptured, logger });
    }

    return { handleCaptured, installFetch, installXHR, dedupe };
  }

  /**
   * Wraps `win.fetch` so every call still resolves with the real, unmodified
   * response. Capture reads a *clone* of the body so the page's own read of
   * the response stream is never consumed or delayed by this bridge.
   * Returns an uninstall function for tests.
   */
  function installFetchCapture({ win, handleCaptured, logger = console } = {}) {
    const target = win || (typeof window !== "undefined" ? window : undefined);
    if (!target || typeof target.fetch !== "function") {
      return () => {};
    }
    const originalFetch = target.fetch;

    target.fetch = function patchedFetch(input, init) {
      return originalFetch.call(target, input, init).then((response) => {
        try {
          const url = typeof input === "string" ? input : (input && input.url) || "";
          const method =
            (init && init.method) || (input && typeof input === "object" && input.method) || "GET";
          if (shouldCapture(url) && typeof response.clone === "function") {
            response
              .clone()
              .text()
              .then((raw) => {
                handleCaptured({
                  source: "fetch",
                  url,
                  method,
                  status: response.status,
                  ok: response.ok,
                  contentType:
                    response.headers && typeof response.headers.get === "function"
                      ? response.headers.get("content-type")
                      : null,
                  raw,
                });
              })
              .catch((err) => {
                safeWarn(logger, `hoops-gm bridge: could not read fetch response body (${err && err.message})`);
              });
          }
        } catch (err) {
          safeWarn(logger, `hoops-gm bridge: fetch capture failed (${err && err.message})`);
        }
        return response;
      });
    };

    return () => {
      target.fetch = originalFetch;
    };
  }

  /**
   * Wraps `win.XMLHttpRequest` with a subclass-like function that returns a
   * genuine original-XHR instance with `open` observed and a `load` listener
   * *added* (never replacing any handler the page itself attaches). Returns
   * an uninstall function for tests.
   */
  function installXHRCapture({ win, handleCaptured, logger = console } = {}) {
    const target = win || (typeof window !== "undefined" ? window : undefined);
    if (!target || typeof target.XMLHttpRequest !== "function") {
      return () => {};
    }
    const OriginalXHR = target.XMLHttpRequest;

    function PatchedXHR(...args) {
      const xhr = new OriginalXHR(...args);
      let capturedMethod = "GET";
      let capturedUrl = "";
      const originalOpen = xhr.open.bind(xhr);
      xhr.open = function patchedOpen(method, url, ...rest) {
        capturedMethod = method;
        capturedUrl = url;
        return originalOpen(method, url, ...rest);
      };
      xhr.addEventListener("load", function onLoad() {
        try {
          if (shouldCapture(capturedUrl)) {
            const contentType =
              typeof xhr.getResponseHeader === "function" ? xhr.getResponseHeader("content-type") : null;
            handleCaptured({
              source: "xhr",
              url: capturedUrl,
              method: capturedMethod,
              status: xhr.status,
              ok: xhr.status >= 200 && xhr.status < 300,
              contentType,
              raw: xhr.responseText,
            });
          }
        } catch (err) {
          safeWarn(logger, `hoops-gm bridge: xhr capture failed (${err && err.message})`);
        }
      });
      return xhr;
    }
    PatchedXHR.prototype = OriginalXHR.prototype;

    target.XMLHttpRequest = PatchedXHR;

    return () => {
      target.XMLHttpRequest = OriginalXHR;
    };
  }

  const capture = {
    ENVELOPE_SCHEMA,
    FXPA_REQ_PATHNAME,
    shouldCapture,
    normalizeBody,
    buildEnvelope,
    computeDedupeKey,
    createDedupeCache,
    createCapture,
  };
  globalThis.HoopsGmCapture = capture;

  // Auto-install only in a real page context, and only once the transport
  // foundation from userscript.js has set itself up. Guarded the same way
  // userscript.js guards its own auto-install, so loading this file in a
  // non-browser context (including these tests) never installs anything.
  if (typeof window !== "undefined" && typeof globalThis.HoopsGmTransport !== "undefined") {
    const installed = createCapture({ transport: globalThis.HoopsGmTransport });
    installed.installFetch(window);
    installed.installXHR(window);
    capture.instance = installed;
  }
})();
