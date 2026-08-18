import { mkdir, readFile, writeFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const root = dirname(fileURLToPath(import.meta.url));
const output = resolve(root, "dist", "hoops-gm.user.js");

// Must match BACKEND_ORIGIN in src/userscript.js. The loopback backend
// serves this exact built file back at USERSCRIPT_PATH — see
// backend/src/hoops_gm/api/routes/userscript.py — which is what lets
// @updateURL/@downloadURL below point at a live, buildable target instead of
// a URL nothing serves.
const BACKEND_ORIGIN = "http://127.0.0.1:8000";
const USERSCRIPT_PATH = "/bridge/userscript.user.js";

// The single source of truth for @version: bump package.json's "version"
// and both the installed script's self-report and its own update check move
// together. A version drift between the two is exactly how "the update
// silently never fires" bugs happen.
const packageJson = JSON.parse(await readFile(resolve(root, "package.json"), "utf8"));
const { version } = packageJson;

// Order matters: userscript.js sets globalThis.HoopsGmTransport, and
// capture.js's auto-install checks for it before wiring fetch/XHR capture.
const sourceFiles = ["userscript.js", "capture.js"];
const sources = await Promise.all(
  sourceFiles.map((name) => readFile(resolve(root, "src", name), "utf8"))
);

const metadata = `// ==UserScript==
// @name         hoops-gm bridge
// @namespace    https://github.com/SR2501/hoops-gm
// @version      ${version}
// @description  Local-only transport and read-only /fxpa/req capture for the hoops-gm Fantrax bridge
// @match        https://www.fantrax.com/fantasy/league/*
// @match        https://fantrax.com/fantasy/league/*
// @grant        GM_getValue
// @grant        GM_setValue
// @grant        GM_registerMenuCommand
// @grant        GM_addElement
// @grant        GM_xmlhttpRequest
// @connect      127.0.0.1
// @run-at       document-start
// @updateURL    ${BACKEND_ORIGIN}${USERSCRIPT_PATH}
// @downloadURL  ${BACKEND_ORIGIN}${USERSCRIPT_PATH}
// ==/UserScript==

`;

await mkdir(dirname(output), { recursive: true });
await writeFile(output, metadata + sources.join("\n"), "utf8");
console.log(`Built ${output}`);
