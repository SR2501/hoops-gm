(() => {
  "use strict";

  const BACKEND_ORIGIN = "http://127.0.0.1:8000";
  const SECRET_KEY = "hoops-gm.bridge-secret";
  const HANDSHAKE_PATH = "/api/v1/bridge/handshake";

  function generateSecret() {
    const bytes = new Uint8Array(32);
    crypto.getRandomValues(bytes);
    return Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0")).join("");
  }

  function getSecret(storage = { get: GM_getValue, set: GM_setValue }) {
    const existing = storage.get(SECRET_KEY, "");
    if (typeof existing === "string" && existing.length >= 64) {
      return existing;
    }
    const generated = generateSecret();
    storage.set(SECRET_KEY, generated);
    return generated;
  }

  function createTransport({
    request = GM_xmlhttpRequest,
    storage = { get: GM_getValue, set: GM_setValue },
    origin = BACKEND_ORIGIN,
  } = {}) {
    const secret = getSecret(storage);

    function send(method, path, body) {
      return new Promise((resolve, reject) => {
        request({
          method,
          url: `${origin}${path}`,
          headers: {
            Accept: "application/json",
            "Content-Type": "application/json",
            "X-Bridge-Secret": secret,
          },
          data: body === undefined ? undefined : JSON.stringify(body),
          timeout: 3000,
          onload: (response) => {
            if (response.status < 200 || response.status >= 300) {
              reject(new Error(`backend returned HTTP ${response.status}`));
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

    return {
      secretKey: SECRET_KEY,
      healthCheck: () => send("GET", "/health"),
      handshake: () => send("POST", HANDSHAKE_PATH, { protocol: 1 }),
    };
  }

  const bridge = { createTransport, getSecret, HANDSHAKE_PATH };
  globalThis.HoopsGmBridge = bridge;

  if (typeof GM_xmlhttpRequest === "function") {
    globalThis.HoopsGmTransport = createTransport();
  }
})();
