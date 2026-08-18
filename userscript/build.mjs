import { mkdir, readFile, writeFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const root = dirname(fileURLToPath(import.meta.url));
const output = resolve(root, "dist", "hoops-gm.user.js");
const packageJsonPath = resolve(root, "package.json");
const packageLockPath = resolve(root, "package-lock.json");

// Order matters: userscript.js sets globalThis.HoopsGmTransport, and
// capture.js's auto-install checks for it before wiring fetch/XHR capture.
const sourceFiles = ["userscript.js", "capture.js"];
const [packageJsonRaw, packageLockRaw, ...sources] = await Promise.all([
  readFile(packageJsonPath, "utf8"),
  readFile(packageLockPath, "utf8"),
  ...sourceFiles.map((name) => readFile(resolve(root, "src", name), "utf8")),
]);
const packageJson = JSON.parse(packageJsonRaw);
const packageLock = JSON.parse(packageLockRaw);
const version = packageJson.version;

if (typeof version !== "string" || !/^\d+\.\d+\.\d+$/.test(version)) {
  throw new Error("userscript/package.json version must be a three-part numeric semver");
}
if (packageLock.version !== version || packageLock.packages?.[""]?.version !== version) {
  throw new Error(
    "userscript package.json and package-lock.json versions differ; use `npm version <version> --no-git-tag-version`"
  );
}

// Must match BACKEND_ORIGIN in src/userscript.js and the route mounted in
// backend/src/hoops_gm/api/routes/userscript.py. Not extracted into a shared
// constant: build.mjs and the userscript sources are already independent
// files by convention in this project (see the duplicated path literals
// between userscript.js and bridge.py), and this URL only ever changes
// together with that route.
const UPDATE_URL = "http://127.0.0.1:8000/bridge/userscript.user.js";
// Tampermonkey keys script identity (and therefore GM storage) by @name plus
// @namespace. These values are deliberately frozen to the 0.1.0/0.2.0
// identity. Changing either would orphan the installed bridge secret and the
// native updater would treat the result as a different userscript.
const SCRIPT_NAME = "hoops-gm bridge";
const SCRIPT_NAMESPACE = "https://github.com/SR2501/hoops-gm";

const metadata = `// ==UserScript==
// @name         ${SCRIPT_NAME}
// @namespace    ${SCRIPT_NAMESPACE}
// @version      ${version}
// @description  Local-only transport and read-only /fxpa/req capture for the hoops-gm Fantrax bridge
// @match        https://www.fantrax.com/fantasy/league/*
// @match        https://fantrax.com/fantasy/league/*
// @noframes
// @grant        GM_getValue
// @grant        GM_setValue
// @grant        GM_registerMenuCommand
// @grant        GM_addElement
// @grant        GM_xmlhttpRequest
// @connect      127.0.0.1
// @run-at       document-start
// @updateURL    ${UPDATE_URL}
// @downloadURL  ${UPDATE_URL}
// ==/UserScript==

`;

await mkdir(dirname(output), { recursive: true });
await writeFile(output, metadata + sources.join("\n"), "utf8");
console.log(`Built ${output}`);
