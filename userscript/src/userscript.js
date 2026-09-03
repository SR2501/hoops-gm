(() => {
  "use strict";

  const BACKEND_ORIGIN = "http://127.0.0.1:8000";
  const SECRET_KEY = "hoops-gm.bridge-secret";
  const HANDSHAKE_PATH = "/api/v1/bridge/handshake";
  const PAYLOADS_PATH = "/api/v1/bridge/payloads";
  const PAIRING_CODE_PATH = "/api/v1/bridge/pairing";
  const PAIR_PATH = "/api/v1/bridge/pair";
  const USERSCRIPT_STATUS_PATH = "/bridge/userscript-status.json";
  const DRAFT_FEED_STATUS_PATH = "/api/v1/drafts/by-fantrax-league/feed";

  function isStoredSecret(value) {
    return typeof value === "string" && (
      /^[0-9a-f]{64}$/i.test(value) || /^[A-Za-z0-9_-]{43}$/.test(value)
    );
  }

  function getSecret(storage = { get: GM_getValue, set: GM_setValue }) {
    const existing = storage.get(SECRET_KEY, "");
    return isStoredSecret(existing) ? existing : null;
  }

  function createTransport({
    request = GM_xmlhttpRequest,
    storage = { get: GM_getValue, set: GM_setValue },
    origin = BACKEND_ORIGIN,
  } = {}) {
    function send(method, path, body, headers = {}, expectedStatus = null) {
      return new Promise((resolve, reject) => {
        const requestHeaders = {
          Accept: "application/json",
          ...headers,
        };
        if (body !== undefined) {
          requestHeaders["Content-Type"] = "application/json";
        }
        request({
          method,
          url: `${origin}${path}`,
          headers: requestHeaders,
          data: body === undefined ? undefined : JSON.stringify(body),
          timeout: 3000,
          onload: (response) => {
            if (response.status < 200 || response.status >= 300) {
              let errorCode = null;
              let detail = null;
              try {
                const payload = JSON.parse(response.responseText);
                errorCode = typeof payload.error === "string" ? payload.error : null;
                detail = typeof payload.detail === "string" ? payload.detail : null;
              } catch {
                // The HTTP status still identifies the failure when the backend
                // cannot provide its stable JSON error envelope.
              }
              const error = new Error(
                `backend returned HTTP ${response.status}${errorCode ? ` (${errorCode})` : ""}`
              );
              error.status = response.status;
              error.code = errorCode;
              error.detail = detail;
              reject(error);
              return;
            }
            if (expectedStatus !== null && response.status !== expectedStatus) {
              reject(
                new Error(
                  `backend returned HTTP ${response.status}; expected HTTP ${expectedStatus}`
                )
              );
              return;
            }
            try {
              resolve(JSON.parse(response.responseText));
            } catch {
              reject(new Error("backend returned invalid JSON"));
            }
          },
          onerror: () => reject(new Error("backend unreachable")),
          ontimeout: () => reject(new Error("backend request timed out")),
          onabort: () => reject(new Error("backend request aborted")),
        });
      });
    }

    function authenticatedSend(method, path, body, expectedStatus = null) {
      const secret = getSecret(storage);
      if (!secret) {
        return Promise.reject(new Error("bridge is not paired"));
      }
      return send(method, path, body, { "X-Bridge-Secret": secret }, expectedStatus);
    }

    return {
      backendOrigin: origin,
      isPaired: () => getSecret(storage) !== null,
      secretKey: SECRET_KEY,
      storeSecret: (secret) => storage.set(SECRET_KEY, secret),
      healthCheck: () => authenticatedSend("GET", "/health"),
      handshake: () => authenticatedSend("POST", HANDSHAKE_PATH, { protocol: 1 }),
      sendPayload: (envelope) =>
        authenticatedSend("POST", PAYLOADS_PATH, envelope, 201).then((response) => {
          if (
            !response ||
            response.status !== "stored" ||
            !Number.isSafeInteger(response.id) ||
            response.id < 1
          ) {
            throw new Error("backend did not acknowledge durable payload storage");
          }
          return response;
        }),
      requestPairingCode: () => send("GET", PAIRING_CODE_PATH),
      pair: (code) => send(
        "POST",
        PAIR_PATH,
        undefined,
        { "X-Hoops-GM-Pairing-Code": code }
      ),
      userscriptStatus: (installedVersion) =>
        send(
          "GET",
          `${USERSCRIPT_STATUS_PATH}?installed_version=${encodeURIComponent(
            typeof installedVersion === "string" ? installedVersion : ""
          )}`
        ),
      draftFeedStatus: (fantraxLeagueId) =>
        send(
          "GET",
          `${DRAFT_FEED_STATUS_PATH}?fantrax_league_id=${encodeURIComponent(
            typeof fantraxLeagueId === "string" ? fantraxLeagueId : ""
          )}`
        ),
    };
  }

  function pairingFailureMessage(error) {
    if (error && /HTTP 401/.test(error.message)) {
      return "Pairing failed: the code is invalid, expired, or has already been used.";
    }
    if (error && /HTTP 409/.test(error.message)) {
      return "Pairing is unavailable because this backend already has a bridge secret.";
    }
    if (error && /not paired|unreachable|timed out/.test(error.message)) {
      return "Pairing could not reach the local hoops-gm backend. Confirm it is running.";
    }
    return "Pairing failed. Check that the local backend is running and try again.";
  }

  async function pairFromMenu({ transport, prompt, alert }) {
    try {
      const pairing = await transport.requestPairingCode();
      if (!pairing || !/^[A-Za-z0-9_-]{12}$/.test(pairing.code)) {
        throw new Error("invalid pairing response");
      }

      alert(
        `hoops-gm bridge pairing code:\n\n${pairing.code}\n\nCopy this code, then paste it into the next prompt. It expires in 10 minutes.`
      );
      const code = prompt("Paste the hoops-gm bridge pairing code:");
      if (code === null) {
        return { status: "cancelled" };
      }

      const response = await transport.pair(code.trim());
      if (!response || !isStoredSecret(response.bridgeSecret)) {
        throw new Error("invalid pairing response");
      }
      transport.storeSecret(response.bridgeSecret);
      alert("hoops-gm bridge paired successfully.");
      return { status: "paired" };
    } catch (error) {
      alert(pairingFailureMessage(error));
      return { status: "failed" };
    }
  }

  function installPairingMenu({
    registerMenuCommand,
    prompt,
    alert,
    transport,
  } = {}) {
    if (typeof registerMenuCommand !== "function" || typeof prompt !== "function" || typeof alert !== "function" || !transport) {
      return false;
    }
    registerMenuCommand("Pair hoops-gm bridge", () => {
      void pairFromMenu({ transport, prompt, alert });
    });
    return true;
  }

  const bridge = {
    createTransport,
    getSecret,
    installPairingMenu,
    isStoredSecret,
    pairFromMenu,
    HANDSHAKE_PATH,
    PAYLOADS_PATH,
    PAIRING_CODE_PATH,
    PAIR_PATH,
    USERSCRIPT_STATUS_PATH,
    DRAFT_FEED_STATUS_PATH,
  };
  globalThis.HoopsGmBridge = bridge;

  if (typeof GM_xmlhttpRequest === "function") {
    const transport = createTransport();
    globalThis.HoopsGmTransport = transport;
    installPairingMenu({
      registerMenuCommand: typeof GM_registerMenuCommand === "function" ? GM_registerMenuCommand : undefined,
      prompt: typeof globalThis.prompt === "function" ? globalThis.prompt : undefined,
      alert: typeof globalThis.alert === "function" ? globalThis.alert : undefined,
      transport,
    });
  }
})();
