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
  // Automatic rendered-view snapshots are a lower-confidence fallback for
  // service-worker-private responses. Keep them bounded and deliberately
  // slow: navigation gets a prompt settled snapshot, while ordinary DOM
  // churn can produce at most one new attempt per minute.
  const AUTO_SNAPSHOT_MAX_CHARS = 250000;
  const AUTO_SNAPSHOT_SETTLE_MS = 2000;
  const AUTO_SNAPSHOT_MAX_SETTLE_MS = 10000;
  const AUTO_SNAPSHOT_NAV_MIN_INTERVAL_MS = 5000;
  const AUTO_SNAPSHOT_MUTATION_MIN_INTERVAL_MS = 60000;
  const AUTO_SNAPSHOT_LOCATION_POLL_MS = 1000;
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
  // Three read-only, best-effort paths remain, plus one guaranteed manual
  // fallback:
  //  1. Cache Storage (`window.caches`) is a *per-origin* store shared by
  //     both `window` and the service worker -- if fx-sw.js persists
  //     responses there (a common Workbox pattern), a page script can
  //     legitimately enumerate and read them. See `startCacheStorageWatcher`
  //     below. This is opportunistic: it depends entirely on Fantrax's own
  //     implementation and is unverified against the live site.
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
  } = {}) {
    const inFlight = new Map();

    function forward(envelope) {
      if (!transport || typeof transport.sendPayload !== "function") {
        return Promise.resolve(false);
      }
      if (dedupe.has(envelope.dedupeKey)) {
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
          return true;
        })
        .catch(() => {
          safeWarn(
            logger,
            `hoops-gm bridge: failed to forward captured payload (${envelope.request.method} ${envelope.request.url})`
          );
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

    // Best-effort, read-only: some /fxpa/req calls are initiated by
    // Fantrax's own service worker rather than page script, so the
    // fetch/XHR patches above never see them (a service worker runs in a
    // separate global scope no page script can instrument). Cache Storage
    // is the one place both worlds can legitimately meet: it is a per-origin
    // store, so if the service worker persists a response there, this page
    // script can read the same entry no differently than reading any other
    // origin-scoped browser storage. This is opportunistic and depends
    // entirely on Fantrax's own implementation -- it may find nothing, and
    // that is an expected, non-error outcome, not a bug.
    if (
      !window[marker].cacheWatcherStarted &&
      typeof window.caches === "object" &&
      window.caches &&
      typeof window.caches.keys === "function" &&
      typeof window.setInterval === "function"
    ) {
      window[marker].cacheWatcherStarted = true;

      const pollCacheStorage = () => {
        // A hidden tab is already timer-throttled by the browser; skipping
        // explicitly keeps this from ever being the thing that competes for
        // a throttled tick during a draft.
        if (typeof document !== "undefined" && document.visibilityState === "hidden") {
          return;
        }
        Promise.resolve()
          .then(() => window.caches.keys())
          .then((cacheNames) =>
            Promise.all(
              (cacheNames || []).map((name) =>
                window.caches
                  .open(name)
                  .then((cache) => cache.keys().then((requests) => ({ cache, requests })))
                  .then(({ cache, requests }) =>
                    Promise.all(
                      requests
                        .filter((request) => matches(request && request.url))
                        .map((request) =>
                          cache
                            .match(request, { ignoreMethod: true })
                            .then((response) => {
                              if (!response || typeof response.clone !== "function") {
                                return undefined;
                              }
                              return response
                                .clone()
                                .text()
                                .then((raw) =>
                                  publish({
                                    source: "cache-storage",
                                    url: request.url,
                                    method: request.method || "GET",
                                    status: response.status,
                                    ok: response.ok,
                                    contentType:
                                      response.headers && typeof response.headers.get === "function"
                                        ? response.headers.get("content-type")
                                        : null,
                                    raw,
                                  })
                                )
                                .catch(() => {});
                            })
                            .catch(() => {})
                        )
                    )
                  )
                  .catch(() => {})
              )
            )
          )
          .catch(() => {
            // Cache Storage inspection is opportunistic; never throw into Fantrax.
          });
      };
      pollCacheStorage();
      window[marker].cacheWatcherIntervalId = window.setInterval(pollCacheStorage, 5000);
    }
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

  /**
   * Clones the selected root (never touches the live DOM) and strips
   * `<script>`/`<style>`/`<noscript>` so no inline script content or
   * stylesheet text is forwarded -- only rendered markup and its visible
   * text/attribute content. Bounded so one export cannot send an unbounded
   * payload.
   */
  function buildDomSnapshotHtml(doc, { maxChars = DOM_SNAPSHOT_MAX_CHARS } = {}) {
    const root = selectSnapshotRoot(doc);
    if (!root || typeof root.cloneNode !== "function") {
      return "";
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
      // These values are not request bodies, but stripping them structurally
      // prevents a typed search/chat value from becoming one by accident.
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
    const html = typeof clone.outerHTML === "string" ? clone.outerHTML : "";
    const limit = Number.isSafeInteger(maxChars) && maxChars > 0
      ? maxChars
      : DOM_SNAPSHOT_MAX_CHARS;
    return html.length > limit
      ? `${html.slice(0, limit)}\n<!-- hoops-gm bridge: truncated at ${limit} chars -->`
      : html;
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
      const html = buildDomSnapshotHtml(doc, { maxChars });
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
      return { captured: false, reason: "unexpected error" };
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
    let lastCaptureAt = Number.NEGATIVE_INFINITY;
    let lastUrl = win.location.href;
    let wasPaired = hasPairedLocalTransport(transport);
    let wasReady = doc.readyState !== "loading";

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
      try {
        const result = await captureRenderedViewSnapshot({ capture, win, doc, logger });
        if (result.captured) {
          lastCaptureAt = nowMs();
        }
      } finally {
        pendingSince = null;
        pendingKind = null;
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
        lastCaptureAt + minInterval
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
    captureRenderedViewSnapshot,
    hasPairedLocalTransport,
    installAutomaticRenderedViewCapture,
    captureManualSnapshot,
    installManualCaptureMenu,
  };
  globalThis.HoopsGmCapture = capture;

  // Auto-install only in a real page context. The capture receiver stays in
  // Tampermonkey's isolated world so forwarding remains GM-privileged; only
  // the narrow response observer is injected into Fantrax's page world.
  if (typeof window !== "undefined" && typeof globalThis.HoopsGmTransport !== "undefined") {
    const transport = globalThis.HoopsGmTransport;
    const installed = createCapture({ transport });
    installed.pageBridge = installPageWorldBridge({ capture: installed, win: window, doc: document });
    installed.renderedViewWatcher = installAutomaticRenderedViewCapture({
      capture: installed,
      transport,
      win: window,
      doc: document,
    });
    capture.instance = installed;
    installManualCaptureMenu({
      registerMenuCommand: typeof GM_registerMenuCommand === "function" ? GM_registerMenuCommand : undefined,
      capture: installed,
      win: window,
      doc: document,
      alert: typeof globalThis.alert === "function" ? globalThis.alert : undefined,
    });
  }
})();
