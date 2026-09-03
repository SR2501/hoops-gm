(() => {
  "use strict";

  // Strictly read-only capture of Fantrax's internal /fxpa/req JSON-RPC
  // endpoint. This module never modifies a request or a response, never
  // blocks the page from receiving its real fetch/XHR result, and never
  // throws into page code: every capture path is wrapped so a bug here can
  // at most silently drop one capture, never break Fantrax's own UI.
  //
  // Network observation captures RESPONSES only. The lower-confidence
  // rendered-view fallback captures a sanitized clone of already-rendered
  // HTML and labels it separately. Outgoing request bodies and all headers
  // (cookie, auth, or otherwise) are never read or forwarded. See ADR-004:
  // /fxpa/req is undocumented internal infrastructure and is read here,
  // never written to.

  const ENVELOPE_SCHEMA = "hoops-gm.bridge-payload.v1";
  const PAGE_EVENT_SCHEMA = "hoops-gm.page-capture.v1";
  const PAGE_EVENT_TYPE = "hoops-gm.bridge.page-capture.v1";
  const FXPA_REQ_PATHNAME = "/fxpa/req";
  const FANTRAX_HOSTS = new Set(["fantrax.com", "www.fantrax.com"]);
  const FANTRAX_LEAGUE_PATH_PREFIX = "/fantasy/league/";
  const LOCAL_BACKEND_ORIGIN = "http://127.0.0.1:8000";
  // Rendered-view snapshots are the only observed source of live draft picks:
  // /fxpa/req is service-worker-private and getDraftPicks returned no picks
  // against a finished draft. Keep capture bounded and deliberately slow.
  const AUTO_SNAPSHOT_MAX_CHARS = 250000;
  const AUTO_SNAPSHOT_SETTLE_MS = 2000;
  const AUTO_SNAPSHOT_MAX_SETTLE_MS = 10000;
  const AUTO_SNAPSHOT_NAV_MIN_INTERVAL_MS = 5000;
  const AUTO_SNAPSHOT_MUTATION_MIN_INTERVAL_MS = 60000;
  const AUTO_SNAPSHOT_LOCATION_POLL_MS = 1000;
  const VERSION_STATUS_MIN_INTERVAL_MS = 60000;
  const FEED_STATUS_MIN_INTERVAL_MS = 60000;
  // FastAPI/Pydantic validates this identifier with Python's Unicode-aware
  // `\S`; ECMAScript's `\s` omits U+001C-U+001F and includes U+FEFF.
  const PYTHON_WHITESPACE =
    /[\t\n\v\f\r \u001c-\u001f\u0085\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]/u;
  const DRAFT_PAGE_PATH = /\/draft(?:\/|$)/;
  const DRAFT_BOARD_ROOT_SELECTOR = ".league-draft-board";
  const DRAFT_BOARD_HEADER_SELECTOR = ".league-draft-board__header";
  const DRAFT_BOARD_BODY_SELECTOR = ".league-draft-board__body";
  const DRAFT_CHAT_ROOT_SELECTOR = ".chat-room";
  // Fixed, not derived from window.location: capture is only ever installed
  // on pages matching the userscript's own narrow @match rule, and a fixed
  // base keeps filtering deterministic and testable outside a browser.
  const CAPTURE_BASE = "https://www.fantrax.com";

  /**
   * @typedef {Object} BridgePayloadEnvelope
   * @property {string} schema
   * @property {"fetch"|"xhr"|"cache-storage"|"rendered-view"|"manual-export"} source
   * @property {string} capturedAt ISO-8601 timestamp
   * @property {{method: string, url: string}} request
   * @property {{status: number|null, ok: boolean, contentType: string|null}} response
   * @property {{raw: string, json: unknown|null, parseError: string|null}} body
   * @property {string} dedupeKey
   */

  // Root cause of the zero-row capture reported against a paired, healthy
  // backend: DevTools shows the relevant /fxpa/req calls initiated by
  // Fantrax's own service worker (fx-sw.js), not by page script. A
  // service worker executes in its own global scope, entirely separate
  // from `window` -- there is no supported browser API, and no
  // Tampermonkey grant, that lets a userscript observe or instrument another
  // origin-scoped script's *internal* `self.fetch()` calls or the response
  // it produces without ever handing it to the page. Monkey-patching
  // `window.fetch`/`XMLHttpRequest` (above and in `installPageWorldHook`)
  // only ever sees requests page script itself issues, so it structurally
  // cannot see a service-worker-originated call. This is a platform
  // boundary, not a bug in the patch.
  //
  // One read-only best-effort path remains, plus one guaranteed manual
  // fallback. A second was tried and is now ruled out:
  //  1. Cache Storage (`window.caches`) is a *per-origin* store shared by
  //     both `window` and the service worker, so if fx-sw.js persisted
  //     responses there -- a common Workbox pattern -- a page script could
  //     legitimately enumerate and read them. **Tried, and verified absent on
  //     a live Fantrax draft room on 2026-08-28.** The origin's Cache Storage
  //     held exactly five entries, all `ngsw:`-prefixed Angular
  //     service-worker *asset* caches (`assets:app:cache`,
  //     `assets:assets:cache`, plus their meta and control databases).
  //     Angular's service-worker configuration distinguishes `assetGroups`
  //     from `dataGroups`, and Fantrax declares only asset groups -- so API
  //     responses are never persisted to Cache Storage at all, and no amount
  //     of polling can find one. The watcher that read this store was removed
  //     with this finding; see the note where it used to run, below. This is
  //     a property of Fantrax's service-worker config, not of our reader, so
  //     re-adding the watcher would only reproduce the same empty result --
  //     but it is worth re-testing if Fantrax ever ships a `dataGroups` entry.
  //  2. A bounded rendered-view snapshot in the isolated world runs after
  //     initial load, SPA navigation, and settled DOM changes. It does not
  //     claim to be the missing raw response; it records the already-rendered
  //     evidence automatically with an explicit lower-confidence source.
  //  3. IndexedDB is the same idea but was not implemented here: its schema
  //     would have to be reverse-engineered per Fantrax version and is far
  //     more likely to drift silently than Cache Storage's simple
  //     Request/Response shape. Left as a documented option, not code.
  //  4. `captureManual`/`captureManualSnapshot` (isolated world, below) is
  //     the guaranteed fallback: an explicit, owner-triggered Tampermonkey
  //     menu command that exports whatever is already rendered on the page
  //     at that moment, independent of which layer produced it.

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

  /**
   * Automatic rendered-view capture is narrower than the userscript metadata
   * alone: it runs only on HTTPS Fantrax league pages with a concrete league
   * path. This check is repeated at capture time so an SPA navigation cannot
   * silently widen the scope after the document-start install.
   */
  function isFantraxLeaguePage(url) {
    if (typeof url !== "string" || url.length === 0) {
      return false;
    }
    try {
      const parsed = new URL(url, CAPTURE_BASE);
      return (
        parsed.protocol === "https:" &&
        FANTRAX_HOSTS.has(parsed.hostname.toLowerCase()) &&
        parsed.pathname.startsWith(FANTRAX_LEAGUE_PATH_PREFIX) &&
        parsed.pathname.length > FANTRAX_LEAGUE_PATH_PREFIX.length
      );
    } catch {
      return false;
    }
  }

  function isFantraxDraftPage(url) {
    if (!isFantraxLeaguePage(url)) {
      return false;
    }
    try {
      return DRAFT_PAGE_PATH.test(new URL(url, CAPTURE_BASE).pathname);
    } catch {
      return false;
    }
  }

  function fantraxLeagueIdFromUrl(url) {
    if (!isFantraxLeaguePage(url)) {
      return null;
    }
    try {
      const parsed = new URL(url, CAPTURE_BASE);
      const encoded = parsed.pathname
        .slice(FANTRAX_LEAGUE_PATH_PREFIX.length)
        .split("/")[0];
      const leagueId = decodeURIComponent(encoded);
      return leagueId.length >= 1 && leagueId.length <= 64 && !PYTHON_WHITESPACE.test(leagueId)
        ? leagueId
        : null;
    } catch {
      return null;
    }
  }

  function isTopLevelWindow(win) {
    try {
      return Boolean(win) && (!win.top || win.top === win);
    } catch {
      return false;
    }
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
      has(key) {
        return seenKeys.has(key);
      },
      remember(key) {
        seenKeys.delete(key);
        seenKeys.set(key, true);
        if (seenKeys.size > maxEntries) {
          const oldest = seenKeys.keys().next().value;
          seenKeys.delete(oldest);
        }
      },
      size() {
        return seenKeys.size;
      },
      clear() {
        seenKeys.clear();
      },
      forget(key) {
        seenKeys.delete(key);
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
    status = null,
  } = {}) {
    const inFlight = new Map();

    /**
     * The status strip must never be able to break the capture it reports
     * on, so every call into it is contained here.
     */
    function report(method, argument) {
      if (!status || typeof status[method] !== "function") {
        return;
      }
      try {
        status[method](argument);
      } catch {
        // Reporting is observational only.
      }
    }

    function forward(envelope) {
      if (!transport || typeof transport.sendPayload !== "function") {
        report("recordRefusal", "no local transport is configured");
        return Promise.resolve(false);
      }
      if (dedupe.has(envelope.dedupeKey)) {
        report("recordDuplicate", envelope.source);
        return Promise.resolve(true);
      }
      const activeDelivery = inFlight.get(envelope.dedupeKey);
      if (activeDelivery) {
        return activeDelivery;
      }

      const delivery = Promise.resolve()
        .then(() => transport.sendPayload(envelope))
        .then(() => {
          dedupe.remember(envelope.dedupeKey);
          report("recordDelivered", envelope.source);
          return true;
        })
        .catch((err) => {
          safeWarn(
            logger,
            `hoops-gm bridge: failed to forward captured payload (${envelope.request.method} ${envelope.request.url})`
          );
          // The reason was previously discarded here. A refused envelope is
          // one of the four ways this bridge fails silently, and the message
          // is the only thing that separates "backend unreachable" from
          // "bridge is not paired" from "HTTP 401" on the page.
          report("recordRefusal", err && err.message);
          return false;
        })
        .finally(() => {
          if (inFlight.get(envelope.dedupeKey) === delivery) {
            inFlight.delete(envelope.dedupeKey);
          }
        });
      inFlight.set(envelope.dedupeKey, delivery);
      return delivery;
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

    function capturePageSnapshot({ source, url, contentType, raw }) {
      try {
        const envelope = buildEnvelope({
          source,
          url,
          method: "GET",
          status: null,
          ok: true,
          contentType: contentType || null,
          raw,
          capturedAtMs: now(),
        });
        return forward(envelope);
      } catch (err) {
        safeWarn(logger, `hoops-gm bridge: page snapshot failed (${err && err.message})`);
        return Promise.resolve(false);
      }
    }

    /**
     * The guaranteed owner-triggered fallback (see `captureManualSnapshot`).
     * It deliberately bypasses `shouldCapture`: the URL is the current
     * Fantrax page, not the internal RPC endpoint.
     */
    function captureManual({ url, contentType, raw }) {
      return capturePageSnapshot({ source: "manual-export", url, contentType, raw });
    }

    /**
     * Lower-confidence automatic fallback. It has the same typed envelope,
     * raw preservation and dedupe as every other source, but repeats the
     * league-page scope check before forwarding.
     */
    function captureRenderedView({ url, raw }) {
      if (!isFantraxLeaguePage(url) || typeof raw !== "string" || raw.length === 0) {
        return Promise.resolve(false);
      }
      return capturePageSnapshot({
        source: "rendered-view",
        url,
        contentType: "text/html",
        raw,
      });
    }

    return {
      handleCaptured,
      installFetch,
      installXHR,
      captureManual,
      captureRenderedView,
      dedupe,
    };
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
    Object.setPrototypeOf(PatchedXHR, OriginalXHR);

    target.XMLHttpRequest = PatchedXHR;

    return () => {
      target.XMLHttpRequest = OriginalXHR;
    };
  }

  function generateChannel(random = globalThis.crypto) {
    const bytes = new Uint8Array(16);
    if (!random || typeof random.getRandomValues !== "function") {
      // The channel is a correlation value, never an authentication secret.
      // A deterministic fallback keeps a missing Web Crypto API from breaking
      // page capture, while the bridge secret remains Tampermonkey-only.
      return `fallback-${Date.now()}-${Math.random()}`;
    }
    random.getRandomValues(bytes);
    return Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0")).join("");
  }

  /**
   * This function is stringified and executed in the page's MAIN world. Keep
   * it self-contained: it has no GM APIs, no bridge secret, and no reference
   * to the isolated userscript. It observes only the response fields emitted
   * below, then sends them to the isolated world with postMessage.
   */
  function installPageWorldHook(channel, eventType) {
    "use strict";
    const schema = "hoops-gm.page-capture.v1";
    const pathname = "/fxpa/req";
    const hosts = new Set(["fantrax.com", "www.fantrax.com"]);
    const marker = "__hoopsGmPageCaptureV1Installed";
    const existing = window[marker];
    if (existing && existing.channels && typeof existing.channels.add === "function") {
      existing.channels.add(channel);
      return;
    }
    const channels = new Set([channel]);
    window[marker] = { channels };

    function matches(url) {
      if (typeof url !== "string" || url.length === 0) {
        return false;
      }
      try {
        const parsed = new URL(url, window.location.href);
        return hosts.has(parsed.hostname.toLowerCase()) && parsed.pathname === pathname;
      } catch {
        return false;
      }
    }

    function publish(details) {
      try {
        for (const activeChannel of channels) {
          window.postMessage(
            {
              schema,
              channel: activeChannel,
              source: details.source,
              url: details.url,
              method: details.method || "GET",
              status: typeof details.status === "number" ? details.status : null,
              ok: Boolean(details.ok),
              contentType: details.contentType || null,
              raw: typeof details.raw === "string" ? details.raw : "",
            },
            window.location.origin
          );
        }
      } catch {
        // Capture is strictly observational; never throw into Fantrax.
      }
    }

    if (typeof window.fetch === "function") {
      const originalFetch = window.fetch;
      window.fetch = function hoopsGmPageFetch(input, init) {
        return originalFetch.call(this, input, init).then((response) => {
          try {
            const url = typeof input === "string" ? input : (input && input.url) || "";
            const method = (init && init.method) || (input && input.method) || "GET";
            if (matches(url) && response && typeof response.clone === "function") {
              response.clone().text().then(
                (raw) => publish({
                  source: "fetch",
                  url,
                  method,
                  status: response.status,
                  ok: response.ok,
                  contentType: response.headers && typeof response.headers.get === "function"
                    ? response.headers.get("content-type")
                    : null,
                  raw,
                }),
                () => {}
              );
            }
          } catch {
            // Keep the page's real response untouched.
          }
          return response;
        });
      };
    }

    if (typeof window.XMLHttpRequest === "function") {
      const OriginalXHR = window.XMLHttpRequest;
      function PageCaptureXHR(...args) {
        const xhr = new OriginalXHR(...args);
        let method = "GET";
        let url = "";
        const originalOpen = xhr.open.bind(xhr);
        xhr.open = function hoopsGmPageOpen(nextMethod, nextUrl, ...rest) {
          method = nextMethod;
          url = nextUrl;
          return originalOpen(nextMethod, nextUrl, ...rest);
        };
        xhr.addEventListener("load", () => {
          try {
            if (matches(url)) {
              publish({
                source: "xhr",
                url,
                method,
                status: xhr.status,
                ok: xhr.status >= 200 && xhr.status < 300,
                contentType: typeof xhr.getResponseHeader === "function"
                  ? xhr.getResponseHeader("content-type")
                  : null,
                raw: xhr.responseText,
              });
            }
          } catch {
            // Keep the page's own XHR event handling untouched.
          }
        });
        return xhr;
      }
      PageCaptureXHR.prototype = OriginalXHR.prototype;
      Object.setPrototypeOf(PageCaptureXHR, OriginalXHR);
      window.XMLHttpRequest = PageCaptureXHR;
    }

    // Cache Storage watcher: REMOVED 2026-08-28, after being verified empty.
    //
    // This is where a `setInterval(pollCacheStorage, 5000)` used to run on
    // every Fantrax league page. It enumerated `window.caches`, matched
    // entries against the `/fxpa/req` filter above, and published anything it
    // found as `source: "cache-storage"`. It was a legitimate hypothesis --
    // Cache Storage is per-origin, so a response written there by fx-sw.js is
    // readable by page script, and persisting API responses there is a common
    // Workbox pattern. It was never verified against the live site, and it
    // was labelled as such.
    //
    // It has now been checked. On a live Fantrax draft room the origin's
    // Cache Storage held five entries, every one an `ngsw:`-prefixed Angular
    // service-worker *asset* cache. Angular's service-worker config separates
    // `assetGroups` from `dataGroups`; Fantrax declares only asset groups, so
    // `/fxpa/req` responses are never written to Cache Storage and the poll
    // could not have succeeded on any tick. The same session captured 49
    // payloads, all `rendered-view` or `manual-export` and none `fxpa`.
    //
    // It was removed for the cost rather than the tidiness: a recurring
    // background timer competes for attention in a tab the browser may be
    // throttling, and the rendered-view path -- the one that does work --
    // already depends on `setTimeout` and `MutationObserver` firing promptly
    // during a draft.
    //
    // The `"cache-storage"` source string is deliberately still accepted by
    // `PAGE_EVENT_SOURCES` and by the backend envelope schema. Nothing emits
    // it now, but it is part of `hoops-gm.bridge-payload.v1`, which the
    // backend validates and which already-stored payloads may carry;
    // retiring a shared schema value is a contract change, not a bridge-local
    // one.
    //
    // Do not re-add this as an obvious missing capability. The finding is
    // about Fantrax's service-worker configuration, not about the reader, so
    // a reimplementation returns the same nothing. It is worth re-testing
    // only if Fantrax ships a `dataGroups` entry -- check for a non-`ngsw:`
    // cache name in DevTools first, which costs seconds and settles it.
  }

  function createPageWorldHookSource(channel) {
    return `;(${installPageWorldHook.toString()})(${JSON.stringify(channel)}, ${JSON.stringify(PAGE_EVENT_TYPE)});`;
  }

  // Sources the page-world hook may legitimately postMessage. "rendered-view"
  // and "manual-export" are deliberately excluded: both are produced directly
  // in the isolated world and are not scoped to the `/fxpa/req` URL filter
  // this receiver re-applies.
  const PAGE_EVENT_SOURCES = new Set(["fetch", "xhr", "cache-storage"]);

  function pageEventDetails(event, { channel, origin, source } = {}) {
    if (!event || event.source !== source || event.origin !== origin) {
      return null;
    }
    const data = event.data;
    if (!data || typeof data !== "object" || Array.isArray(data)) {
      return null;
    }
    if (
      data.schema !== PAGE_EVENT_SCHEMA ||
      data.channel !== channel ||
      !PAGE_EVENT_SOURCES.has(data.source) ||
      typeof data.url !== "string" ||
      typeof data.method !== "string" ||
      (data.status !== null && (!Number.isInteger(data.status) || data.status < 0)) ||
      typeof data.ok !== "boolean" ||
      (data.contentType !== null && typeof data.contentType !== "string") ||
      typeof data.raw !== "string"
    ) {
      return null;
    }
    if (!shouldCapture(data.url)) {
      return null;
    }
    return {
      source: data.source,
      url: data.url,
      method: data.method,
      status: data.status,
      ok: data.ok,
      contentType: data.contentType,
      raw: data.raw,
    };
  }

  /**
   * Installs the isolated-world receiver first, then injects the hook into the
   * page's MAIN world. GM_addElement is Tampermonkey's CSP-safe script
   * injection path. The plain DOM fallback exists for compatible execution
   * modes, but may be rejected by a site CSP and reports that failure instead
   * of pretending capture is active.
   */
  function installPageWorldBridge({
    capture,
    win = typeof window !== "undefined" ? window : undefined,
    doc = typeof document !== "undefined" ? document : undefined,
    addElement = typeof GM_addElement === "function" ? GM_addElement : undefined,
    channel = generateChannel(),
    logger = console,
  } = {}) {
    if (!capture || !win || !doc || !win.location || typeof win.addEventListener !== "function") {
      return { installed: false, uninstall: () => {} };
    }
    const origin = win.location.origin;
    const onMessage = (event) => {
      const details = pageEventDetails(event, { channel, origin, source: win });
      if (details) {
        capture.handleCaptured(details);
      }
    };
    win.addEventListener("message", onMessage, false);
    const source = createPageWorldHookSource(channel);
    let injected = false;
    try {
      if (typeof addElement === "function") {
        const result = addElement(doc.documentElement || doc.head, "script", { textContent: source });
        injected = true;
        if (result && typeof result.catch === "function") {
          result.catch(() => safeWarn(logger, "hoops-gm bridge: page-world hook injection was rejected"));
        }
      } else if (typeof doc.createElement === "function") {
        const script = doc.createElement("script");
        script.textContent = source;
        const parent = doc.documentElement || doc.head;
        if (!parent || typeof parent.appendChild !== "function") {
          throw new Error("document has no script injection target");
        }
        parent.appendChild(script);
        if (typeof script.remove === "function") {
          script.remove();
        }
        injected = true;
      }
    } catch (err) {
      safeWarn(logger, `hoops-gm bridge: page-world hook injection failed (${err && err.message})`);
    }
    return {
      installed: injected,
      channel,
      uninstall: () => win.removeEventListener("message", onMessage, false),
    };
  }

  // ---------------------------------------------------------------------------
  // Rendered-view fallbacks: automatic (bounded) and explicit manual export
  // ---------------------------------------------------------------------------
  //
  // This runs entirely in Tampermonkey's isolated world, which shares the
  // live DOM with the page (DOM access is not a CSP-restricted operation --
  // only script/resource loading is). It never depends on which layer
  // produced a response, so it works even when both the fetch/XHR patch and
  // the Cache Storage watcher find nothing. It captures a clone of already
  // -rendered content the owner is looking at; it never triggers a new
  // request and never touches Fantrax's own state.

  const DOM_SNAPSHOT_MAX_CHARS = 500000;
  // Checked in order; the first exposed and non-empty value wins. These are
  // common SSR/state-container globals across frameworks, checked
  // opportunistically -- Fantrax exposing none of them is an expected,
  // non-error outcome, and the DOM snapshot below is still taken.
  const APP_STATE_GLOBALS = ["__NEXT_DATA__", "__NUXT__", "__INITIAL_STATE__", "__APOLLO_STATE__"];
  // Tried in order; the first element found is snapshotted. `body` is the
  // guaranteed last resort so the export always has *something* rather than
  // silently finding nothing on an unfamiliar page layout.
  const SNAPSHOT_ROOT_SELECTORS = ["main", "#root", "#app", "body"];

  /**
   * Best-effort read of a framework's exposed client-side state object.
   * Never throws: a hostile or throwing getter on `win` must not break the
   * manual export.
   */
  function readExposedAppState(win) {
    for (const key of APP_STATE_GLOBALS) {
      try {
        const value = win[key];
        if (value !== undefined && value !== null) {
          const json = JSON.stringify(value);
          if (typeof json === "string" && json.length > 0) {
            return { key, json };
          }
        }
      } catch {
        // A throwing getter must not break the manual export; try the next.
      }
    }
    return null;
  }

  function selectSnapshotRoot(doc) {
    for (const selector of SNAPSHOT_ROOT_SELECTORS) {
      try {
        const element = doc.querySelector(selector);
        if (element) {
          return element;
        }
      } catch {
        // An invalid selector in an unfamiliar DOM must not abort the export.
      }
    }
    return doc.documentElement || null;
  }

  function cloneAndSanitizeSnapshotRoot(root) {
    if (!root || typeof root.cloneNode !== "function") {
      return null;
    }
    const clone = root.cloneNode(true);
    if (typeof clone.querySelectorAll === "function") {
      for (const node of Array.from(clone.querySelectorAll("script, style, noscript"))) {
        if (typeof node.remove === "function") {
          node.remove();
        }
      }
      // Never carry form-control state into an automatic or manual snapshot.
      // Only the detached clone is changed; the live Fantrax DOM is untouched.
      for (const node of Array.from(
        clone.querySelectorAll("input, textarea, select, option")
      )) {
        if (typeof node.removeAttribute === "function") {
          for (const attribute of ["value", "checked", "selected"]) {
            node.removeAttribute(attribute);
          }
        }
        if (
          typeof node.tagName === "string" &&
          node.tagName.toLowerCase() === "textarea" &&
          "textContent" in node
        ) {
          node.textContent = "";
        }
      }
    }
    return clone;
  }

  function snapshotLimit(maxChars, fallback = DOM_SNAPSHOT_MAX_CHARS) {
    return Number.isSafeInteger(maxChars) && maxChars > 0
      ? maxChars
      : fallback;
  }

  function truncateSnapshotHtml(html, limit) {
    const marker = truncationMarker(limit);
    if (marker.length > limit) {
      return "";
    }
    const prefixBudget = limit - marker.length - 1;
    // A raw slice can end inside an attribute, causing the parser to treat the
    // marker as attribute text. Quotes and ">" are legal in comments and
    // attributes, so scan those states rather than searching for one byte.
    let state = "text";
    let quote = null;
    let lastSafeBoundary = -1;
    for (let index = 0; index < Math.min(prefixBudget, html.length); index += 1) {
      const char = html[index];
      if (state === "comment") {
        if (index + 2 < prefixBudget && html.startsWith("-->", index)) {
          lastSafeBoundary = index + 2;
          state = "text";
          index += 2;
        }
        continue;
      }
      if (state === "text") {
        if (html.startsWith("<!--", index)) {
          state = "comment";
          index += 3;
        } else if (char === "<") {
          state = "tag";
        } else {
          lastSafeBoundary = index;
        }
        continue;
      }
      if (state === "tag") {
        if (quote !== null) {
          if (char === quote) {
            quote = null;
          }
          continue;
        }
        if (char === '"' || char === "'") {
          quote = char;
        } else if (char === ">") {
          lastSafeBoundary = index;
          state = "text";
        }
      } else {
        // Defensive reset: state is internal, but never let an unexpected value
        // turn a future ">" into a claimed safe boundary.
        state = "text";
        quote = null;
      }
    }
    const prefix = lastSafeBoundary >= 0 ? html.slice(0, lastSafeBoundary + 1) : "";
    return prefix ? `${prefix}\n${marker}` : marker;
  }

  function truncationMarker(limit) {
    return `<!-- hoops-gm bridge: truncated at ${limit} chars -->`;
  }

  function chatOmissionMarker(limit) {
    return `<!-- hoops-gm bridge: auxiliary chat omitted at ${limit} char cap -->`;
  }

  function snapshotCloneHtml(
    clone,
    {
      maxChars,
      fallbackMaxChars = DOM_SNAPSHOT_MAX_CHARS,
      refuseTruncation = false,
    } = {}
  ) {
    const html = clone && typeof clone.outerHTML === "string" ? clone.outerHTML : "";
    const limit = snapshotLimit(maxChars, fallbackMaxChars);
    if (html.length <= limit) {
      return html;
    }
    if (refuseTruncation) {
      throw new Error(
        `draft board snapshot is ${html.length} chars, exceeding the ${limit}-char ` +
        "automatic capture cap; no partial board was sent"
      );
    }
    return truncateSnapshotHtml(html, limit);
  }

  /**
   * Clones the selected root (never touches the live DOM) and strips
   * `<script>`/`<style>`/`<noscript>` so no inline script content or
   * stylesheet text is forwarded -- only rendered markup and its visible
   * text/attribute content. Bounded so one export cannot send an unbounded
   * payload.
   */
  function buildDomSnapshotHtml(doc, { maxChars = DOM_SNAPSHOT_MAX_CHARS } = {}) {
    const root = selectSnapshotRoot(doc);
    const clone = cloneAndSanitizeSnapshotRoot(root);
    if (!clone) {
      return "";
    }
    return snapshotCloneHtml(clone, { maxChars });
  }

  function buildDraftBoardSnapshotHtml(doc, { maxChars = AUTO_SNAPSHOT_MAX_CHARS } = {}) {
    let root;
    let chatRoot;
    try {
      root = doc.querySelector(DRAFT_BOARD_ROOT_SELECTOR);
      chatRoot = doc.querySelector(DRAFT_CHAT_ROOT_SELECTOR);
    } catch {
      root = null;
      chatRoot = null;
    }
    const clone = cloneAndSanitizeSnapshotRoot(root);
    if (!clone || typeof clone.querySelector !== "function") {
      throw new Error(
        `draft page has no cloneable ${DRAFT_BOARD_ROOT_SELECTOR} subtree; no snapshot was sent`
      );
    }
    const missing = [
      DRAFT_BOARD_HEADER_SELECTOR,
      DRAFT_BOARD_BODY_SELECTOR,
    ].filter((selector) => !clone.querySelector(selector));
    if (missing.length > 0) {
      throw new Error(
        `draft board snapshot is missing ${missing.join(" and ")}; no partial board was sent`
      );
    }
    const limit = snapshotLimit(maxChars, AUTO_SNAPSHOT_MAX_CHARS);
    const boardHtml = snapshotCloneHtml(clone, {
      maxChars,
      fallbackMaxChars: AUTO_SNAPSHOT_MAX_CHARS,
      refuseTruncation: true,
    });
    const chatClone = cloneAndSanitizeSnapshotRoot(chatRoot);
    const chatHtml = chatClone && typeof chatClone.outerHTML === "string"
      ? chatClone.outerHTML
      : "";
    if (!chatHtml) {
      return boardHtml;
    }
    const combined = `${boardHtml}\n${chatHtml}`;
    if (combined.length <= limit) {
      return combined;
    }
    const withoutChat = `${boardHtml}\n${chatOmissionMarker(limit)}`;
    return withoutChat.length <= limit ? withoutChat : boardHtml;
  }

  /**
   * The auto path intentionally captures rendered HTML only. It never reads
   * framework state, request objects, headers, cookies, local/session storage,
   * or service-worker internals. The selected root is cloned and sanitized by
   * `buildDomSnapshotHtml`; no live page node is changed.
   */
  async function captureRenderedViewSnapshot({
    capture,
    win = typeof window !== "undefined" ? window : undefined,
    doc = typeof document !== "undefined" ? document : undefined,
    logger = console,
    maxChars = AUTO_SNAPSHOT_MAX_CHARS,
  } = {}) {
    if (
      !capture ||
      typeof capture.captureRenderedView !== "function" ||
      !win ||
      !doc ||
      !win.location ||
      !isTopLevelWindow(win) ||
      !isFantraxLeaguePage(win.location.href)
    ) {
      return { captured: false, reason: "automatic rendered-view capture is out of scope" };
    }
    if (doc.visibilityState === "hidden") {
      return { captured: false, reason: "page is hidden" };
    }
    try {
      const html = isFantraxDraftPage(win.location.href)
        ? buildDraftBoardSnapshotHtml(doc, { maxChars })
        : buildDomSnapshotHtml(doc, { maxChars });
      if (!html) {
        return { captured: false, reason: "no exportable content found on this page" };
      }
      const ok = await capture.captureRenderedView({ url: win.location.href, raw: html });
      return ok
        ? { captured: true, reason: "rendered-view" }
        : { captured: false, reason: "capture rejected the rendered view" };
    } catch (err) {
      safeWarn(
        logger,
        `hoops-gm bridge: automatic rendered-view capture failed (${err && err.message})`
      );
      return {
        captured: false,
        reason: err && typeof err.message === "string" ? err.message : "unexpected error",
        refusal: true,
      };
    }
  }

  /**
   * True only for the real paired transport created by userscript.js. Exact
   * origin equality is deliberate: automatic broad DOM capture must never be
   * enabled for a dependency-injected remote transport.
   */
  function hasPairedLocalTransport(transport) {
    if (
      !transport ||
      transport.backendOrigin !== LOCAL_BACKEND_ORIGIN ||
      typeof transport.isPaired !== "function"
    ) {
      return false;
    }
    try {
      return transport.isPaired() === true;
    } catch {
      return false;
    }
  }

  // ---------------------------------------------------------------------
  // Status strip
  //
  // The bridge's failure mode is silence. An unpaired script, a refused
  // envelope, a stale build and a draft that has not started all look
  // identical from the Fantrax page -- which is the page the owner is
  // looking at during a draft. This surface exists to make those four
  // distinguishable *where he already is*. It does not prevent any of them.
  //
  // It reports only what this userscript observed directly: its own running
  // @version, its own pairing state, and the outcome of its own forwards. It
  // deliberately does NOT report picks the feed recognised. That number is
  // Feed status is resolved only through the backend's external-league-id
  // contract. Never list drafts or guess "the newest": a confident count for
  // the wrong draft is worse than an explicit identity refusal.
  //
  // Hard boundary: this must never show a price, a value, a suggested bid or
  // a ranking. Those belong to `bridge-overlay` and carry the Model gate with
  // them. If a number a decision rests on appears here, this has become the
  // wrong component.
  // ---------------------------------------------------------------------

  const STATUS_TEXT_MAX_CHARS = 120;
  // Mirrors the shape check in test/build.test.js. A transport error should
  // never contain the bridge secret -- none of userscript.js's rejection
  // messages include it -- but this text is the one capture-derived string
  // that reaches the DOM, so the guarantee is enforced here rather than
  // assumed of every future error path.
  const SECRET_SHAPED = /[0-9a-fA-F]{32,}|[A-Za-z0-9_-]{43,}/g;
  const THREE_PART_VERSION = /^\d+\.\d+\.\d+$/;

  function versionParts(value) {
    return typeof value === "string" && THREE_PART_VERSION.test(value)
      ? value.split(".").map(Number)
      : null;
  }

  function compareVersions(left, right) {
    const leftParts = versionParts(left);
    const rightParts = versionParts(right);
    if (!leftParts || !rightParts) {
      return null;
    }
    for (let index = 0; index < leftParts.length; index += 1) {
      if (leftParts[index] !== rightParts[index]) {
        return leftParts[index] < rightParts[index] ? -1 : 1;
      }
    }
    return 0;
  }

  /**
   * Collapses an error message to one short, printable, secret-free line.
   * Returns null for anything that reduces to nothing.
   */
  function sanitizeStatusText(value, maxChars = STATUS_TEXT_MAX_CHARS) {
    if (typeof value !== "string") {
      return null;
    }
    const collapsed = value
      .replace(/[\u0000-\u001f\u007f]+/g, " ")
      .replace(/\s+/g, " ")
      .trim();
    if (collapsed.length === 0) {
      return null;
    }
    const redacted = collapsed.replace(SECRET_SHAPED, "[redacted]");
    return redacted.length > maxChars ? `${redacted.slice(0, maxChars - 1)}\u2026` : redacted;
  }

  function pad2(value) {
    return String(value).padStart(2, "0");
  }

  /** Local wall-clock, because that is the clock the owner is drafting on. */
  function formatClock(ms) {
    const when = new Date(ms);
    if (Number.isNaN(when.getTime())) {
      return null;
    }
    return `${pad2(when.getHours())}:${pad2(when.getMinutes())}:${pad2(when.getSeconds())}`;
  }

  /**
   * Deliberately coarse. An age is what makes a stale feed visible, but a
   * per-second age would rewrite the DOM every second for the whole draft.
   * Bucketing to "just now" then whole minutes bounds the rewrite to once a
   * minute while keeping the only distinction that matters: whether the last
   * capture was recent or a long time ago.
   */
  function formatAge(ageMs) {
    if (!Number.isFinite(ageMs) || ageMs < 0) {
      return null;
    }
    const seconds = Math.floor(ageMs / 1000);
    if (seconds < 45) {
      return "just now";
    }
    const minutes = Math.round(seconds / 60);
    if (minutes < 90) {
      return `${minutes}m ago`;
    }
    return `${Math.round(minutes / 60)}h ago`;
  }

  function countReasonMap(value) {
      if (!value || typeof value !== "object" || Array.isArray(value)) {
        return 0;
      }
      return Object.values(value).reduce(
        (total, count) => total + (Number.isSafeInteger(count) && count >= 0 ? count : 0),
        0
      );
    }

    function plural(count, singular, pluralValue = `${singular}s`) {
      return `${count} ${count === 1 ? singular : pluralValue}`;
    }

    function formatFeedState(safe) {
      const state = typeof safe.feedStatus === "string" ? safe.feedStatus : "checking";
      const leagueId = sanitizeStatusText(safe.feedLeagueId, 64);
      const report = safe.feedReport;
      if (state === "checking") {
        return {
          line: leagueId ? `feed ${leagueId}: checking local draft` : "feed: checking page identity",
          warning: null,
          ok: false,
        };
      }
      if (state === "invalid_page_id") {
        return {
          line: "feed unavailable",
          warning: "FEED ID UNAVAILABLE: current Fantrax URL has no valid league id",
          ok: false,
        };
      }
      if (state === "not_found") {
        return {
          line: leagueId ? `feed ${leagueId}: no local draft` : "feed: no local draft",
          warning: "NO LOCAL DRAFT: this Fantrax league is not linked to a persisted draft",
          ok: false,
        };
      }
      if (state === "ambiguous") {
        return {
          line: leagueId ? `feed ${leagueId}: ambiguous local draft` : "feed: ambiguous local draft",
          warning: "AMBIGUOUS LOCAL DRAFT: multiple persisted drafts match this Fantrax league",
          ok: false,
        };
      }
      if (state !== "available" || !report) {
        return {
          line: leagueId ? `feed ${leagueId}: status uncheckable` : "feed: status uncheckable",
          warning: `FEED STATUS UNCHECKABLE: ${
            sanitizeStatusText(safe.feedReason) || "local feed contract unavailable"
          }`,
          ok: false,
        };
      }

      const skipped = countReasonMap(report.skipped);
      const retryable = countReasonMap(report.retryable);
      const lineParts = [
        `draft ${report.draft_id} feed`,
        `observed ${report.observation_count}`,
        `applied ${report.applied_count}`,
        `pending ${report.pending_count}`,
        `skipped ${skipped}`,
      ];
      if (retryable > 0) {
        lineParts.push(`retryable ${retryable}`);
      }

      const warnings = [];
      if (typeof report.context_unavailable === "string" && report.context_unavailable) {
        warnings.push(`FEED CONTEXT UNAVAILABLE: ${sanitizeStatusText(report.context_unavailable)}`);
      }
      if (Array.isArray(report.blocked) && report.blocked.length > 0) {
        warnings.push(
          `FEED BLOCKED: ${report.blocked
            .map((reason) => sanitizeStatusText(reason))
            .filter(Boolean)
            .join(", ")}`
        );
      }
      if (retryable > 0) {
        warnings.push(`FEED RETRYING: ${plural(retryable, "state conflict")} still pending`);
      }
      const silent = Array.isArray(report.freshness)
        ? report.freshness.filter((source) => source && source.silent === true)
        : [];
      if (silent.length > 0) {
        const sources = silent.map((source) => {
          const transport = sanitizeStatusText(source.transport, 32) || "unknown source";
          const age = source.contact_is_known ? source.contact_age_seconds : source.age_seconds;
          const ageText = Number.isFinite(age) ? `${Math.round(age)}s old` : "never seen";
          return `${transport} ${ageText} (limit ${Math.round(source.silence_threshold_seconds)}s)`;
        });
        warnings.push(`FEED STALE/SILENT: ${sources.join(", ")}`);
      }
      const reconciliation = report.reconciliation;
      if (reconciliation && typeof reconciliation === "object") {
        const disagreementCount = Array.isArray(reconciliation.disagreements)
          ? reconciliation.disagreements.length
          : 0;
        const bridgeOnly = Array.isArray(reconciliation.only_bridge)
          ? reconciliation.only_bridge.length
          : 0;
        const officialOnly = Array.isArray(reconciliation.only_official)
          ? reconciliation.only_official.length
          : 0;
        const findings = [];
        if (disagreementCount > 0) {
          findings.push(plural(disagreementCount, "disagreement"));
        }
        if (bridgeOnly > 0) {
          findings.push(`${bridgeOnly} bridge-only`);
        }
        if (officialOnly > 0) {
          findings.push(`${officialOnly} official-only`);
        }
        if (findings.length > 0) {
          warnings.push(`FEED RECONCILIATION: ${findings.join(", ")}`);
        }
        if (reconciliation.independence && reconciliation.independence.independent === false) {
          warnings.push(
            `FEED UNCORROBORATED: ${
              sanitizeStatusText(reconciliation.independence.reason) ||
              "the readings are not independent"
            }`
          );
        }
        if (Array.isArray(reconciliation.caveats) && reconciliation.caveats.length > 0) {
          warnings.push(
            `FEED CAVEAT: ${sanitizeStatusText(reconciliation.caveats[0]) || "see dashboard"}`
          );
        }
      }
      const regressions = Array.isArray(report.board_regressions)
        ? report.board_regressions.length
        : 0;
      if (regressions > 0) {
        warnings.push(
          `BOARD REGRESSION: ${plural(regressions, "pick")} disappeared; prior state retained`
        );
      }
      return {
        line: lineParts.join(" \u00b7 "),
        warning: warnings.length > 0 ? warnings.join(" | ") : null,
        ok: warnings.length === 0,
      };
    }

  /**
   * The whole rendering decision, as a pure function of state. Kept separate
   * from the DOM so the wording of every failure mode is testable without a
   * browser.
   *
   * @returns {{headline: string, detail: string, feed: string, refusal: string|null, ok: boolean}}
   */
  function formatStatusLines(state, { nowMs = Date.now() } = {}) {
    const safe = state || {};
    const version = typeof safe.version === "string" && safe.version ? `v${safe.version}` : "bridge";
    const paired = safe.paired === true;
    const forwarded = Number.isSafeInteger(safe.forwarded) ? safe.forwarded : 0;
    const duplicates = Number.isSafeInteger(safe.duplicates) ? safe.duplicates : 0;
    const refusal = sanitizeStatusText(safe.lastRefusal);
    const versionStatus = typeof safe.versionStatus === "string"
      ? safe.versionStatus
      : "uncheckable";
    const sourceVersion = typeof safe.sourceVersion === "string" ? safe.sourceVersion : null;
    const servedVersion = typeof safe.servedVersion === "string" ? safe.servedVersion : null;
    const versionReason = sanitizeStatusText(safe.versionReason);
    const feed = formatFeedState(safe);

    const currentLabel = versionStatus === "current" ? " \u00b7 update current" : "";
    const headline =
      `hoops-gm ${version} \u00b7 ${paired ? "paired" : "NOT PAIRED"}${currentLabel}`;

    let detail;
    if (!paired) {
      // Advice, never a block: the page keeps working either way.
      detail = "not sending \u00b7 pair from the Tampermonkey menu";
    } else if (forwarded === 0 && duplicates === 0) {
      detail = "no captures yet";
    } else {
      const parts = [`${forwarded} sent`];
      if (duplicates > 0) {
        // "Captured, byte-identical to one already sent" is a different fact
        // from "captured nothing", and on a draft board it means the view has
        // not changed rather than that the bridge has stopped.
        parts.push(`${duplicates} unchanged`);
      }
      const clock = Number.isFinite(safe.lastCaptureAtMs) ? formatClock(safe.lastCaptureAtMs) : null;
      if (clock) {
        const age = formatAge(nowMs - safe.lastCaptureAtMs);
        parts.push(age ? `${clock} (${age})` : clock);
      }
      if (typeof safe.lastSource === "string" && safe.lastSource) {
        // Which path produced it is load-bearing: `/fxpa/req` is unreachable,
        // so a healthy-looking count made entirely of `rendered-view`
        // snapshots is the expected state, not evidence of RPC capture.
        parts.push(safe.lastSource);
      }
      detail = parts.join(" \u00b7 ");
    }

    let versionWarning = null;
    if (versionStatus === "checking") {
      versionWarning = "update currency: checking local source and served build";
    } else if (versionStatus === "update_available") {
      versionWarning = sourceVersion
        ? `UPDATE AVAILABLE: installed v${safe.version}; source/served v${sourceVersion} \u00b7 run Tampermonkey update check, then reload`
        : "UPDATE AVAILABLE: run Tampermonkey update check, then reload";
    } else if (versionStatus === "mismatch") {
      versionWarning = sourceVersion && servedVersion && sourceVersion !== servedVersion
        ? `UPDATE REFUSED: served v${servedVersion} does not match source v${sourceVersion} \u00b7 run npm run build`
        : `UPDATE STATUS MISMATCH: ${versionReason || "installed and source versions disagree"}`;
    } else if (versionStatus !== "current") {
      versionWarning = `UPDATE STATUS UNCHECKABLE: ${versionReason || "local version contract unavailable"}`;
    }

    const warnings = [
      versionWarning,
      refusal ? `refused: ${refusal}` : null,
      feed.warning,
    ].filter(Boolean);
    return {
      headline,
      detail,
      feed: feed.line,
      refusal: warnings.length > 0 ? warnings.join(" | ") : null,
      ok: paired && refusal === null && versionStatus === "current" && feed.ok,
    };
  }

  function isNonNegativeInteger(value) {
    return Number.isSafeInteger(value) && value >= 0;
  }

  function isReasonMap(value) {
    return Boolean(value) &&
      typeof value === "object" &&
      !Array.isArray(value) &&
      Object.values(value).every(isNonNegativeInteger);
  }

  function isFeedStatusResponse(report) {
    return Boolean(report) &&
      isNonNegativeInteger(report.draft_id) &&
      report.draft_id > 0 &&
      typeof report.as_of === "string" &&
      !Number.isNaN(Date.parse(report.as_of)) &&
      (report.context_unavailable === null || typeof report.context_unavailable === "string") &&
      Array.isArray(report.freshness) &&
      report.freshness.every(
        (source) =>
          source &&
          typeof source.transport === "string" &&
          typeof source.silent === "boolean" &&
          Number.isFinite(source.silence_threshold_seconds) &&
          isNonNegativeInteger(source.instant_count)
      ) &&
      (report.reconciliation === null ||
        (typeof report.reconciliation === "object" &&
          report.reconciliation !== null &&
          Array.isArray(report.reconciliation.disagreements) &&
          Array.isArray(report.reconciliation.only_bridge) &&
          Array.isArray(report.reconciliation.only_official) &&
          Array.isArray(report.reconciliation.caveats) &&
          report.reconciliation.independence &&
          typeof report.reconciliation.independence.independent === "boolean")) &&
      isNonNegativeInteger(report.observation_count) &&
      isNonNegativeInteger(report.applied_count) &&
      isNonNegativeInteger(report.pending_count) &&
      Array.isArray(report.blocked) &&
      report.blocked.every((reason) => typeof reason === "string") &&
      isReasonMap(report.retryable) &&
      isReasonMap(report.skipped) &&
      Array.isArray(report.skipped_by_participant) &&
      isReasonMap(report.unattributed_skipped) &&
      isNonNegativeInteger(report.last_sequence) &&
      Array.isArray(report.board_regressions);
  }

  /**
   * Event-driven state for the status strip. No timer of its own: callers
   * push transitions in as they happen, and `observeContext` is called from
   * the rendered-view watcher's existing tick.
   */
  function createBridgeStatus({ version = null, now = () => Date.now() } = {}) {
    const state = {
      version: typeof version === "string" && version ? version : null,
      versionStatus: "checking",
      sourceVersion: null,
      servedVersion: null,
      versionReason: null,
      paired: false,
      forwarded: 0,
      duplicates: 0,
      lastCaptureAtMs: null,
      lastSource: null,
      lastRefusal: null,
      lastRefusalSource: null,
      lastRefusalAtMs: null,
      feedStatus: "checking",
      feedLeagueId: null,
      feedReport: null,
      feedReason: null,
    };
    const scopedRefusals = new Map();
    let unscopedRefusal = null;
    let refusalSequence = 0;
    const listeners = new Set();

    function nowMs() {
      try {
        const value = Number(now());
        return Number.isFinite(value) ? value : Date.now();
      } catch {
        return Date.now();
      }
    }

    function emit() {
      for (const listener of Array.from(listeners)) {
        try {
          listener(snapshot());
        } catch {
          // A broken renderer must never break capture.
        }
      }
    }

    function snapshot() {
      return { ...state };
    }

    function syncRefusalState() {
      const candidates = [
        ...(unscopedRefusal ? [unscopedRefusal] : []),
        ...scopedRefusals.values(),
      ];
      const latest = candidates.reduce(
        (selected, candidate) =>
          !selected || candidate.sequence > selected.sequence ? candidate : selected,
        null
      );
      if (!latest) {
        state.lastRefusal = null;
        state.lastRefusalSource = null;
        state.lastRefusalAtMs = null;
        return;
      }
      state.lastRefusal = latest.message;
      state.lastRefusalSource = latest.source;
      state.lastRefusalAtMs = latest.atMs;
    }

    function clearRefusalFor(source) {
      unscopedRefusal = null;
      syncRefusalState();
    }

    return {
      snapshot,
      subscribe(listener) {
        if (typeof listener !== "function") {
          return () => {};
        }
        listeners.add(listener);
        try {
          listener(snapshot());
        } catch {
          // As above: a first render that throws must not reject the
          // subscription or propagate into capture.
        }
        return () => listeners.delete(listener);
      },
      recordDelivered(source) {
        state.forwarded += 1;
        state.lastCaptureAtMs = nowMs();
        state.lastSource = typeof source === "string" && source ? source : null;
        clearRefusalFor(state.lastSource);
        emit();
      },
      recordDuplicate(source) {
        state.duplicates += 1;
        state.lastCaptureAtMs = nowMs();
        state.lastSource = typeof source === "string" && source ? source : null;
        clearRefusalFor(state.lastSource);
        emit();
      },
      recordRefusal(message, source = null, recoveryToken = null) {
        const refusalSource = typeof source === "string" && source ? source : null;
        const refusal = {
          message: sanitizeStatusText(message) || "unknown error",
          source: refusalSource,
          atMs: nowMs(),
          sequence: refusalSequence += 1,
          recoveryToken: Number.isSafeInteger(recoveryToken) ? recoveryToken : null,
        };
        if (refusalSource === null) {
          unscopedRefusal = refusal;
        } else {
          scopedRefusals.set(refusalSource, refusal);
        }
        syncRefusalState();
        emit();
      },
      recordRecovery(source, recoveryToken) {
        const recoverySource = typeof source === "string" && source ? source : null;
        if (recoverySource === null) {
          return;
        }
        const refusal = scopedRefusals.get(recoverySource);
        if (
          !refusal ||
          !Number.isSafeInteger(recoveryToken) ||
          (
            refusal.recoveryToken !== null &&
            recoveryToken <= refusal.recoveryToken
          )
        ) {
          return;
        }
        scopedRefusals.delete(recoverySource);
        syncRefusalState();
        emit();
      },
      observeContext({ paired } = {}) {
        state.paired = paired === true;
        // Emitted unconditionally: the strip needs a tick to re-age its
        // "last capture" line, and it suppresses DOM writes itself when the
        // rendered text is unchanged.
        emit();
      },
      recordVersionChecking() {
        state.versionStatus = "checking";
        state.sourceVersion = null;
        state.servedVersion = null;
        state.versionReason = null;
        emit();
      },
      recordVersionStatus(report) {
        const knownStatus = report && [
          "current",
          "update_available",
          "mismatch",
          "uncheckable",
        ].includes(report.status);
        const installedMatches = report && report.installed_version === state.version;
        const sourceVersion =
          report && versionParts(report.source_version) ? report.source_version : null;
        const servedVersion =
          report && versionParts(report.served_version) ? report.served_version : null;
        const currentIsConsistent =
          report && report.status !== "current"
            ? true
            : installedMatches && sourceVersion === state.version && servedVersion === state.version;
        const updateIsConsistent =
          report && report.status !== "update_available"
            ? true
            : installedMatches &&
              sourceVersion !== null &&
              sourceVersion === servedVersion &&
              compareVersions(state.version, sourceVersion) === -1;
        const mismatchIsConsistent =
          report && report.status !== "mismatch"
            ? true
            : installedMatches && sourceVersion !== null && servedVersion !== null;

        if (
          !knownStatus ||
          !currentIsConsistent ||
          !updateIsConsistent ||
          !mismatchIsConsistent
        ) {
          state.versionStatus = "uncheckable";
          state.sourceVersion = sourceVersion;
          state.servedVersion = servedVersion;
          state.versionReason = "invalid local version status response";
        } else {
          state.versionStatus = report.status;
          state.sourceVersion = sourceVersion;
          state.servedVersion = servedVersion;
          state.versionReason =
            typeof report.reason === "string" && report.reason
              ? report.reason.replaceAll("_", " ")
              : null;
        }
        emit();
      },
      recordVersionUncheckable(message) {
        state.versionStatus = "uncheckable";
        state.sourceVersion = null;
        state.servedVersion = null;
        state.versionReason = sanitizeStatusText(message) || "local version contract unavailable";
        emit();
      },
      recordFeedChecking(leagueId) {
        state.feedStatus = "checking";
        state.feedLeagueId = sanitizeStatusText(leagueId, 64);
        state.feedReport = null;
        state.feedReason = null;
        emit();
      },
      recordFeedStatus(report, leagueId) {
        state.feedLeagueId = sanitizeStatusText(leagueId, 64);
        state.feedReport = null;
        state.feedReason = null;
        if (!isFeedStatusResponse(report)) {
          state.feedStatus = "uncheckable";
          state.feedReason = "invalid local feed status response";
        } else {
          state.feedStatus = "available";
          state.feedReport = report;
        }
        emit();
      },
      recordFeedUnavailable(kind, message, leagueId = null) {
        state.feedStatus = [
          "invalid_page_id",
          "not_found",
          "ambiguous",
          "uncheckable",
        ].includes(kind)
          ? kind
          : "uncheckable";
        state.feedLeagueId = sanitizeStatusText(leagueId, 64);
        state.feedReport = null;
        state.feedReason = sanitizeStatusText(message) || "local feed contract unavailable";
        emit();
      },
    };
  }

  /**
   * Revalidates update currency without owning a timer. Callers lend it an
   * existing lifecycle tick; the minimum interval bounds requests, and only
   * the newest request generation may publish a result.
   */
  function createVersionStatusRevalidator({
    transport,
    status,
    installedVersion = null,
    now = () => Date.now(),
    minIntervalMs = VERSION_STATUS_MIN_INTERVAL_MS,
  } = {}) {
    const interval = Math.max(1000, Number(minIntervalMs) || VERSION_STATUS_MIN_INTERVAL_MS);
    let stopped = false;
    let lastAttemptAt = Number.NEGATIVE_INFINITY;
    let requestGeneration = 0;

    function nowMs() {
      try {
        const value = Number(now());
        return Number.isFinite(value) ? value : Date.now();
      } catch {
        return Date.now();
      }
    }

    function recordIfCurrent(generation, callback) {
      if (!stopped && generation === requestGeneration) {
        callback();
      }
    }

    function recheck() {
      if (
        stopped ||
        !transport ||
        typeof transport.userscriptStatus !== "function" ||
        !status ||
        typeof status.recordVersionChecking !== "function" ||
        typeof status.recordVersionStatus !== "function" ||
        typeof status.recordVersionUncheckable !== "function"
      ) {
        if (
          !stopped &&
          status &&
          typeof status.recordVersionUncheckable === "function"
        ) {
          status.recordVersionUncheckable("local version status transport unavailable");
        }
        return false;
      }

      const current = nowMs();
      if (current - lastAttemptAt < interval) {
        return false;
      }
      lastAttemptAt = current;
      const generation = requestGeneration += 1;
      status.recordVersionChecking();
      Promise.resolve()
        .then(() => transport.userscriptStatus(installedVersion))
        .then(
          (report) => recordIfCurrent(
            generation,
            () => status.recordVersionStatus(report)
          ),
          (error) => recordIfCurrent(
            generation,
            () => status.recordVersionUncheckable(error && error.message)
          )
        );
      return true;
    }

    return {
      recheck,
      stop() {
        stopped = true;
        requestGeneration += 1;
      },
    };
  }

  /**
   * Resolves feed status for the current page's exact external league id.
   * It borrows the rendered-view watcher lifecycle, owns no timer, clears a
   * previous report before refreshing, and lets only the newest generation
   * publish.
   */
  function createFeedStatusRevalidator({
    transport,
    status,
    now = () => Date.now(),
    minIntervalMs = FEED_STATUS_MIN_INTERVAL_MS,
  } = {}) {
    const interval = Math.max(1000, Number(minIntervalMs) || FEED_STATUS_MIN_INTERVAL_MS);
    let stopped = false;
    let lastAttemptAt = Number.NEGATIVE_INFINITY;
    let lastLeagueId = null;
    let lastContextKey = null;
    let requestGeneration = 0;

    function nowMs() {
      try {
        const value = Number(now());
        return Number.isFinite(value) ? value : Date.now();
      } catch {
        return Date.now();
      }
    }

    function publishFailure(error, leagueId) {
      const code = error && typeof error.code === "string" ? error.code : null;
      if (code === "draft_for_fantrax_league_not_found") {
        status.recordFeedUnavailable("not_found", code, leagueId);
      } else if (code === "draft_for_fantrax_league_ambiguous") {
        status.recordFeedUnavailable("ambiguous", code, leagueId);
      } else {
        status.recordFeedUnavailable(
          "uncheckable",
          error && error.message ? error.message : "local feed status request failed",
          leagueId
        );
      }
    }

    function recheck(url) {
      if (
        stopped ||
        !transport ||
        typeof transport.draftFeedStatus !== "function" ||
        !status ||
        typeof status.recordFeedChecking !== "function" ||
        typeof status.recordFeedStatus !== "function" ||
        typeof status.recordFeedUnavailable !== "function"
      ) {
        if (!stopped && status && typeof status.recordFeedUnavailable === "function") {
          status.recordFeedUnavailable(
            "uncheckable",
            "local feed status transport unavailable"
          );
        }
        return false;
      }

      const leagueId = fantraxLeagueIdFromUrl(url);
      const contextKey = leagueId === null ? `invalid:${String(url || "")}` : `league:${leagueId}`;
      if (leagueId === null) {
        if (contextKey !== lastContextKey) {
          requestGeneration += 1;
          lastContextKey = contextKey;
          lastLeagueId = null;
          status.recordFeedUnavailable(
            "invalid_page_id",
            "current Fantrax URL has no valid league id"
          );
        }
        return false;
      }

      const current = nowMs();
      const leagueChanged = leagueId !== lastLeagueId;
      if (!leagueChanged && current - lastAttemptAt < interval) {
        return false;
      }
      lastContextKey = contextKey;
      lastLeagueId = leagueId;
      lastAttemptAt = current;
      const generation = requestGeneration += 1;
      status.recordFeedChecking(leagueId);
      Promise.resolve()
        .then(() => transport.draftFeedStatus(leagueId))
        .then(
          (report) => {
            if (!stopped && generation === requestGeneration && leagueId === lastLeagueId) {
              status.recordFeedStatus(report, leagueId);
            }
          },
          (error) => {
            if (!stopped && generation === requestGeneration && leagueId === lastLeagueId) {
              publishFailure(error, leagueId);
            }
          }
        );
      return true;
    }

    return {
      recheck,
      stop() {
        stopped = true;
        requestGeneration += 1;
      },
    };
  }

  const STATUS_HOST_STYLES = [
    // `all: initial` first, so Fantrax's inherited font, colour and direction
    // cannot reach into the shadow tree. Everything after it overrides that
    // reset for this one element.
    ["all", "initial"],
    ["position", "fixed"],
    ["left", "8px"],
    ["bottom", "8px"],
    ["z-index", "2147483000"],
    // The strip advises; it never overrides. With pointer events off it is
    // structurally incapable of swallowing a click meant for the draft board,
    // which is the only way an informational surface could cost a pick.
    ["pointer-events", "none"],
  ];

  const STATUS_BOX_STYLES = [
    ["font-family", "ui-monospace, SFMono-Regular, Menlo, Consolas, monospace"],
    ["font-size", "11px"],
    ["line-height", "1.5"],
    ["letter-spacing", "0.2px"],
    ["padding", "6px 9px"],
    ["border-radius", "6px"],
    ["background", "rgba(17, 19, 24, 0.92)"],
    ["color", "rgb(226, 232, 240)"],
    ["box-shadow", "0 1px 6px rgba(0, 0, 0, 0.35)"],
    ["white-space", "nowrap"],
    ["max-width", "60vw"],
    ["overflow", "hidden"],
    ["text-overflow", "ellipsis"],
  ];

  const STATUS_OK_BORDER = "1px solid rgba(74, 222, 128, 0.55)";
  const STATUS_ALERT_BORDER = "1px solid rgba(251, 191, 36, 0.75)";

  function applyStyles(element, pairs) {
    if (!element || !element.style || typeof element.style.setProperty !== "function") {
      return;
    }
    for (const [property, value] of pairs) {
      try {
        element.style.setProperty(property, value);
      } catch {
        // An unsupported property must not stop the rest of the strip.
      }
    }
  }

  /**
   * Renders the status strip into a closed shadow root.
   *
   * Shadow DOM in both directions: Fantrax's Angular stylesheets cannot
   * restyle this, and nothing here leaks into their page. Every style is set
   * through the CSSOM rather than a `<style>` element or a `style` attribute,
   * because a `style-src` CSP on fantrax.com would block those two and
   * silently leave an unstyled strip -- CSP does not restrict CSSOM writes.
   *
   * Text is assigned with `textContent`, never `innerHTML`: a refusal message
   * is capture-derived text and must never be parsed as markup.
   */
  function installStatusStrip({
    status,
    win = typeof window !== "undefined" ? window : undefined,
    doc = typeof document !== "undefined" ? document : undefined,
    now = () => Date.now(),
    logger = console,
  } = {}) {
    const notInstalled = { installed: false, uninstall: () => {} };
    if (
      !status ||
      typeof status.subscribe !== "function" ||
      !win ||
      !doc ||
      typeof doc.createElement !== "function" ||
      !win.location ||
      !isTopLevelWindow(win) ||
      !isFantraxLeaguePage(win.location.href)
    ) {
      return notInstalled;
    }

    let host;
    let shadow;
    let box;
    let headlineNode;
    let detailNode;
    let feedNode;
    let refusalNode;
    try {
      host = doc.createElement("div");
      if (typeof host.attachShadow !== "function") {
        return notInstalled;
      }
      applyStyles(host, STATUS_HOST_STYLES);
      shadow = host.attachShadow({ mode: "closed" });
      box = doc.createElement("div");
      applyStyles(box, STATUS_BOX_STYLES);
      headlineNode = doc.createElement("div");
      detailNode = doc.createElement("div");
      feedNode = doc.createElement("div");
      refusalNode = doc.createElement("div");
      applyStyles(refusalNode, [["color", "rgb(252, 211, 77)"]]);
      box.appendChild(headlineNode);
      box.appendChild(detailNode);
      box.appendChild(feedNode);
      box.appendChild(refusalNode);
      shadow.appendChild(box);
    } catch (err) {
      safeWarn(logger, `hoops-gm bridge: status strip could not be built (${err && err.message})`);
      return notInstalled;
    }

    let mounted = false;
    let stopped = false;
    let visible = true;
    let lastRendered = null;

    function nowMs() {
      try {
        const value = Number(now());
        return Number.isFinite(value) ? value : Date.now();
      } catch {
        return Date.now();
      }
    }

    function mount() {
      if (mounted || stopped) {
        return;
      }
      // Prefer `body`. Capture installs at document-start, so during parse
      // `body` may not exist yet -- appending to `documentElement` then puts
      // the host where the parser is still building, so that fallback is
      // taken only once parsing has finished and `body` is genuinely absent.
      const parent = doc.body || (doc.readyState !== "loading" ? doc.documentElement : null);
      if (!parent || typeof parent.appendChild !== "function") {
        return;
      }
      try {
        parent.appendChild(host);
        mounted = true;
      } catch (err) {
        safeWarn(logger, `hoops-gm bridge: status strip could not mount (${err && err.message})`);
      }
    }

    function render(state) {
      if (stopped) {
        return;
      }
      // Before the short-circuit below: a state that renders identically must
      // still be able to mount, or a strip whose first render happened at
      // document-start would depend entirely on the DOMContentLoaded listener.
      mount();
      const lines = formatStatusLines(state, { nowMs: nowMs() });
      const signature =
        `${visible}|${lines.headline}|${lines.detail}|${lines.feed}|${lines.refusal || ""}`;
      if (signature === lastRendered) {
        // The watcher tick calls this once a second for the whole draft.
        // Skipping an identical write keeps that from being a DOM mutation
        // per second on the page Fantrax is also mutating.
        return;
      }
      lastRendered = signature;
      try {
        headlineNode.textContent = lines.headline;
        detailNode.textContent = lines.detail;
        feedNode.textContent = lines.feed;
        refusalNode.textContent = lines.refusal || "";
        applyStyles(refusalNode, [["display", lines.refusal ? "block" : "none"]]);
        applyStyles(box, [["border", lines.ok ? STATUS_OK_BORDER : STATUS_ALERT_BORDER]]);
        applyStyles(host, [["display", visible ? "block" : "none"]]);
      } catch (err) {
        safeWarn(logger, `hoops-gm bridge: status strip render failed (${err && err.message})`);
      }
    }

    const unsubscribe = status.subscribe(render);

    const onReady = () => mount();
    if (!mounted && typeof doc.addEventListener === "function") {
      // Capture installs at document-start, so `doc.body` may not exist yet.
      doc.addEventListener("DOMContentLoaded", onReady, { once: true });
    }
    mount();

    return {
      installed: true,
      host,
      shadowRoot: shadow,
      render: () => render(status.snapshot()),
      isVisible: () => visible,
      setVisible: (next) => {
        visible = next === true;
        // Hiding is deliberately not persisted. A remembered "hidden" would
        // recreate exactly the silence this strip exists to break, on a later
        // page load where nobody remembers switching it off.
        render(status.snapshot());
      },
      uninstall: () => {
        stopped = true;
        if (typeof unsubscribe === "function") {
          unsubscribe();
        }
        if (typeof doc.removeEventListener === "function") {
          doc.removeEventListener("DOMContentLoaded", onReady);
        }
        if (host && typeof host.remove === "function") {
          try {
            host.remove();
          } catch {
            // Teardown is best-effort; never throw into the page.
          }
        }
        mounted = false;
      },
    };
  }

  /**
   * Registers the Tampermonkey menu toggle. The menu lives outside the page,
   * so the strip itself never needs to accept a click to be dismissable.
   */
  function installStatusStripMenu({ registerMenuCommand, strip } = {}) {
    if (typeof registerMenuCommand !== "function" || !strip || !strip.installed) {
      return false;
    }
    registerMenuCommand("hoops-gm: show/hide status strip", () => {
      try {
        strip.setVisible(!strip.isVisible());
      } catch {
        // A failed toggle must never propagate into the page.
      }
    });
    return true;
  }

  /**
   * Installs a read-only rendered-view watcher in Tampermonkey's isolated
   * world. It snapshots after DOM settle on initial load, SPA URL changes, and
   * later settled child-list changes. A navigation may capture at most once
   * per 5 seconds; ordinary DOM churn at most once per minute. Exact-body
   * dedupe in createCapture is an independent second bound.
   */
  function installAutomaticRenderedViewCapture({
    capture,
    transport,
    win = typeof window !== "undefined" ? window : undefined,
    doc = typeof document !== "undefined" ? document : undefined,
    MutationObserverCtor,
    now = () => Date.now(),
    setTimeoutFn,
    clearTimeoutFn,
    setIntervalFn,
    clearIntervalFn,
    settleMs = AUTO_SNAPSHOT_SETTLE_MS,
    maxSettleMs = AUTO_SNAPSHOT_MAX_SETTLE_MS,
    navigationMinIntervalMs = AUTO_SNAPSHOT_NAV_MIN_INTERVAL_MS,
    mutationMinIntervalMs = AUTO_SNAPSHOT_MUTATION_MIN_INTERVAL_MS,
    locationPollMs = AUTO_SNAPSHOT_LOCATION_POLL_MS,
    status = null,
    onRelevantContext = null,
    logger = console,
  } = {}) {
    const notInstalled = { installed: false, uninstall: () => {} };
    if (
      !capture ||
      typeof capture.captureRenderedView !== "function" ||
      !transport ||
      transport.backendOrigin !== LOCAL_BACKEND_ORIGIN ||
      !win ||
      !doc ||
      !win.location ||
      !isTopLevelWindow(win) ||
      !isFantraxLeaguePage(win.location.href)
    ) {
      return notInstalled;
    }

    const scheduleTimeout =
      setTimeoutFn ||
      (typeof win.setTimeout === "function" ? win.setTimeout.bind(win) : undefined);
    const cancelTimeout =
      clearTimeoutFn ||
      (typeof win.clearTimeout === "function" ? win.clearTimeout.bind(win) : undefined);
    const scheduleInterval =
      setIntervalFn ||
      (typeof win.setInterval === "function" ? win.setInterval.bind(win) : undefined);
    const cancelInterval =
      clearIntervalFn ||
      (typeof win.clearInterval === "function" ? win.clearInterval.bind(win) : undefined);
    if (typeof scheduleTimeout !== "function" || typeof cancelTimeout !== "function") {
      return notInstalled;
    }

    const observerType =
      MutationObserverCtor ||
      (typeof win.MutationObserver === "function" ? win.MutationObserver : undefined);
    const settleDelay = Math.max(0, Number(settleMs) || 0);
    const settleDeadlineDelay = Math.max(settleDelay, Number(maxSettleMs) || settleDelay);
    const navigationInterval = Math.max(0, Number(navigationMinIntervalMs) || 0);
    const mutationInterval = Math.max(
      navigationInterval,
      Number(mutationMinIntervalMs) || navigationInterval
    );
    const pollInterval = Math.max(250, Number(locationPollMs) || 1000);

    let stopped = false;
    let timeoutId = null;
    let intervalId = null;
    let observer = null;
    let observing = false;
    let pendingSince = null;
    let pendingKind = null;
    let lastAttemptAt = Number.NEGATIVE_INFINITY;
    let attemptSequence = 0;
    let lastUrl = win.location.href;
    let wasPaired = hasPairedLocalTransport(transport);
    let wasReady = doc.readyState !== "loading";

    function reportContext(paired) {
      if (!status || typeof status.observeContext !== "function") {
        return;
      }
      try {
        status.observeContext({ paired });
      } catch {
        // The strip must never be able to stop the capture watcher.
      }
    }

    function nowMs() {
      try {
        const value = Number(now());
        return Number.isFinite(value) ? value : Date.now();
      } catch {
        return Date.now();
      }
    }

    function resetPending() {
      if (timeoutId !== null) {
        cancelTimeout(timeoutId);
        timeoutId = null;
      }
      pendingSince = null;
      pendingKind = null;
    }

    async function runSnapshot() {
      timeoutId = null;
      // This request is now running, not pending. A mutation arriving while
      // transport is awaited starts a new mutation cycle and must use the
      // mutation interval rather than inheriting this request's navigation kind.
      pendingSince = null;
      pendingKind = null;
      if (
        stopped ||
        doc.visibilityState === "hidden" ||
        !isFantraxLeaguePage(win.location.href)
      ) {
        return;
      }
      if (!hasPairedLocalTransport(transport)) {
        resetPending();
        return;
      }
      lastAttemptAt = nowMs();
      const attemptToken = attemptSequence += 1;
      const attemptUrl = win.location.href;
      const attemptIsDraft = isFantraxDraftPage(attemptUrl);
      const result = await captureRenderedViewSnapshot({ capture, win, doc, logger });
      if (
        result.captured &&
        attemptIsDraft &&
        status &&
        typeof status.recordRecovery === "function"
      ) {
        try {
          status.recordRecovery("rendered-view", attemptToken);
        } catch {
          // The strip must never be able to stop the capture watcher.
        }
      } else if (
        !result.captured &&
        result.refusal === true &&
        status &&
        typeof status.recordRefusal === "function"
      ) {
        try {
          status.recordRefusal(
            result.reason,
            attemptIsDraft ? "rendered-view" : null,
            attemptIsDraft ? attemptToken : null
          );
        } catch {
          // The strip must never be able to stop the capture watcher.
        }
      }
    }

    function requestSnapshot(kind = "mutation") {
      if (
        stopped ||
        doc.visibilityState === "hidden" ||
        !isFantraxLeaguePage(win.location.href) ||
        !hasPairedLocalTransport(transport)
      ) {
        return false;
      }
      const requestedKind = kind === "mutation" ? "mutation" : "navigation";
      const current = nowMs();
      if (pendingSince === null) {
        pendingSince = current;
        pendingKind = requestedKind;
      } else if (requestedKind === "navigation" && pendingKind === "mutation") {
        // A route change supersedes an old same-view mutation cycle and gets
        // its own settle window.
        pendingSince = current;
        pendingKind = "navigation";
      }
      const minInterval =
        pendingKind === "mutation" ? mutationInterval : navigationInterval;
      const quietAt = current + settleDelay;
      const deadlineAt = pendingSince + settleDeadlineDelay;
      const dueAt = Math.max(
        Math.min(quietAt, deadlineAt),
        lastAttemptAt + minInterval
      );
      if (timeoutId !== null) {
        cancelTimeout(timeoutId);
      }
      timeoutId = scheduleTimeout(runSnapshot, Math.max(0, dueAt - current));
      return true;
    }

    function attachObserver() {
      if (
        observing ||
        typeof observerType !== "function" ||
        !doc.documentElement
      ) {
        return;
      }
      try {
        observer = new observerType(() => {
          requestSnapshot("mutation");
        });
        observer.observe(doc.documentElement, { childList: true, subtree: true });
        observing = true;
      } catch (err) {
        safeWarn(
          logger,
          `hoops-gm bridge: rendered-view observer unavailable (${err && err.message})`
        );
      }
    }

    function checkContext() {
      if (stopped) {
        return;
      }
      const nextUrl = win.location.href;
      const paired = hasPairedLocalTransport(transport);
      const ready = doc.readyState !== "loading";
      // The status strip rides this existing tick rather than starting its
      // own interval -- the same recurring-timer cost that removing the Cache
      // Storage poll was about. The strip suppresses DOM writes when its
      // rendered text is unchanged, so an unchanged tick costs nothing.
      reportContext(paired);
      if (
        doc.visibilityState !== "hidden" &&
        typeof onRelevantContext === "function"
      ) {
        try {
          // Invalid/non-league SPA navigation is relevant because it must clear
          // the old league's evidence and invalidate any in-flight response.
          onRelevantContext(nextUrl);
        } catch {
          // A status recheck must never stop the capture watcher.
        }
      }
      if (nextUrl !== lastUrl) {
        lastUrl = nextUrl;
        resetPending();
        if (isFantraxLeaguePage(nextUrl)) {
          requestSnapshot("navigation");
        }
      }
      if (ready && !wasReady) {
        attachObserver();
        requestSnapshot("navigation");
      }
      if (paired && !wasPaired && isFantraxLeaguePage(nextUrl)) {
        resetPending();
        requestSnapshot("navigation");
      }
      wasReady = ready;
      wasPaired = paired;
    }

    const onDocumentReady = () => {
      wasReady = true;
      attachObserver();
      requestSnapshot("navigation");
    };
    const onNavigationEvent = () => checkContext();
    const onVisibilityChange = () => {
      checkContext();
      if (doc.visibilityState !== "hidden") {
        resetPending();
        requestSnapshot("navigation");
      }
    };

    if (typeof win.addEventListener === "function") {
      win.addEventListener("popstate", onNavigationEvent, false);
      win.addEventListener("hashchange", onNavigationEvent, false);
    }
    if (typeof doc.addEventListener === "function") {
      doc.addEventListener("visibilitychange", onVisibilityChange, false);
      if (doc.readyState === "loading") {
        doc.addEventListener("DOMContentLoaded", onDocumentReady, { once: true });
      }
    }

    attachObserver();
    reportContext(wasPaired);
    if (
      doc.visibilityState !== "hidden" &&
      typeof onRelevantContext === "function"
    ) {
      try {
        onRelevantContext(win.location.href);
      } catch {
        // As above: currency reporting cannot stop capture.
      }
    }
    if (doc.readyState !== "loading") {
      requestSnapshot("navigation");
    }
    if (typeof scheduleInterval === "function") {
      intervalId = scheduleInterval(checkContext, pollInterval);
    }

    return {
      installed: true,
      requestSnapshot,
      checkContext,
      uninstall: () => {
        stopped = true;
        resetPending();
        if (intervalId !== null && typeof cancelInterval === "function") {
          cancelInterval(intervalId);
        }
        if (observer && typeof observer.disconnect === "function") {
          observer.disconnect();
        }
        if (typeof win.removeEventListener === "function") {
          win.removeEventListener("popstate", onNavigationEvent, false);
          win.removeEventListener("hashchange", onNavigationEvent, false);
        }
        if (typeof doc.removeEventListener === "function") {
          doc.removeEventListener("visibilitychange", onVisibilityChange, false);
          doc.removeEventListener("DOMContentLoaded", onDocumentReady);
        }
      },
    };
  }

  /**
   * The owner-triggered manual export. Prefers an exposed app-state object
   * (structured JSON, easier to parse later) and falls back to a DOM
   * snapshot of the page's main content. Returns `{ captured, reason }`
   * rather than throwing so a menu command handler can report the outcome.
   */
  async function captureManualSnapshot({
    capture,
    win = typeof window !== "undefined" ? window : undefined,
    doc = typeof document !== "undefined" ? document : undefined,
    logger = console,
  } = {}) {
    if (!capture || typeof capture.captureManual !== "function" || !win || !doc || !win.location) {
      return { captured: false, reason: "manual capture is not available in this context" };
    }
    try {
      const appState = readExposedAppState(win);
      const html = appState ? "" : buildDomSnapshotHtml(doc);
      const raw = appState ? appState.json : html;
      if (!raw) {
        return { captured: false, reason: "no exportable content found on this page" };
      }
      const ok = await capture.captureManual({
        url: win.location.href,
        contentType: appState ? "application/json" : "text/html",
        raw,
      });
      return ok
        ? { captured: true, reason: appState ? `app-state:${appState.key}` : "dom-snapshot" }
        : { captured: false, reason: "capture failed while building the envelope" };
    } catch (err) {
      safeWarn(logger, `hoops-gm bridge: manual capture failed (${err && err.message})`);
      return { captured: false, reason: "unexpected error" };
    }
  }

  /**
   * Registers the Tampermonkey menu command for the manual export. Dependency
   * -injected so it is testable without a browser or Tampermonkey.
   */
  function installManualCaptureMenu({ registerMenuCommand, capture, win, doc, alert, logger = console } = {}) {
    if (typeof registerMenuCommand !== "function" || !capture) {
      return false;
    }
    registerMenuCommand("hoops-gm: capture current Fantrax view", () => {
      void captureManualSnapshot({ capture, win, doc, logger }).then((result) => {
        if (typeof alert === "function") {
          try {
            alert(
              result.captured
                ? "hoops-gm bridge: stored the current page for later review."
                : `hoops-gm bridge: nothing stored (${result.reason}).`
            );
          } catch {
            // A broken alert must never propagate into the page.
          }
        }
      });
    });
    return true;
  }

  const capture = {
    ENVELOPE_SCHEMA,
    PAGE_EVENT_SCHEMA,
    PAGE_EVENT_TYPE,
    FXPA_REQ_PATHNAME,
    shouldCapture,
    isFantraxLeaguePage,
    isFantraxDraftPage,
    fantraxLeagueIdFromUrl,
    normalizeBody,
    buildEnvelope,
    computeDedupeKey,
    createDedupeCache,
    createCapture,
    createPageWorldHookSource,
    generateChannel,
    installPageWorldBridge,
    pageEventDetails,
    readExposedAppState,
    selectSnapshotRoot,
    buildDomSnapshotHtml,
    buildDraftBoardSnapshotHtml,
    captureRenderedViewSnapshot,
    hasPairedLocalTransport,
    installAutomaticRenderedViewCapture,
    sanitizeStatusText,
    formatClock,
    formatAge,
    formatStatusLines,
    createBridgeStatus,
    createVersionStatusRevalidator,
    createFeedStatusRevalidator,
    installStatusStrip,
    installStatusStripMenu,
    captureManualSnapshot,
    installManualCaptureMenu,
  };
  globalThis.HoopsGmCapture = capture;

  // Auto-install only in a real page context. The capture receiver stays in
  // Tampermonkey's isolated world so forwarding remains GM-privileged; only
  // the narrow response observer is injected into Fantrax's page world.
  if (typeof window !== "undefined" && typeof globalThis.HoopsGmTransport !== "undefined") {
    const transport = globalThis.HoopsGmTransport;
    // GM_info needs no @grant and is always present under Tampermonkey. The
    // running build's own @version is here because a stale served artifact is
    // one of the four silent failures: on 2026-08-28 the browser correctly
    // reported "no update available" for a build ten days older than the
    // source that declared it, and nothing on the page said so.
    const runningVersion =
      typeof GM_info !== "undefined" && GM_info && GM_info.script && GM_info.script.version
        ? String(GM_info.script.version)
        : null;
    const status = createBridgeStatus({ version: runningVersion });
    const installed = createCapture({ transport, status });
    installed.pageBridge = installPageWorldBridge({ capture: installed, win: window, doc: document });
    installed.status = status;
    installed.statusStrip = installStatusStrip({ status, win: window, doc: document });
    installed.versionStatusRevalidator = createVersionStatusRevalidator({
      transport,
      status,
      installedVersion: runningVersion,
    });
    installed.versionStatusRevalidator.recheck();
    installed.feedStatusRevalidator = createFeedStatusRevalidator({
      transport,
      status,
    });
    installed.feedStatusRevalidator.recheck(window.location.href);
    installed.renderedViewWatcher = installAutomaticRenderedViewCapture({
      capture: installed,
      transport,
      win: window,
      doc: document,
      status,
      onRelevantContext: (url) => {
        if (isFantraxLeaguePage(url)) {
          installed.versionStatusRevalidator.recheck();
        }
        installed.feedStatusRevalidator.recheck(url);
      },
    });
    capture.instance = installed;
    installStatusStripMenu({
      registerMenuCommand: typeof GM_registerMenuCommand === "function" ? GM_registerMenuCommand : undefined,
      strip: installed.statusStrip,
    });
    installManualCaptureMenu({
      registerMenuCommand: typeof GM_registerMenuCommand === "function" ? GM_registerMenuCommand : undefined,
      capture: installed,
      win: window,
      doc: document,
      alert: typeof globalThis.alert === "function" ? globalThis.alert : undefined,
    });
  }
})();
