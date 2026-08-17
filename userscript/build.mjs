import { mkdir, readFile, writeFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const root = dirname(fileURLToPath(import.meta.url));
const output = resolve(root, "dist", "hoops-gm.user.js");

// Order matters: userscript.js sets globalThis.HoopsGmTransport, and
// capture.js's auto-install checks for it before wiring fetch/XHR capture.
const sourceFiles = ["userscript.js", "capture.js"];
const sources = await Promise.all(
  sourceFiles.map((name) => readFile(resolve(root, "src", name), "utf8"))
);

const metadata = `// ==UserScript==
// @name         hoops-gm bridge
// @namespace    https://github.com/SR2501/hoops-gm
// @version      0.2.0
// @description  Local-only transport and read-only /fxpa/req capture for the hoops-gm Fantrax bridge
// @match        https://www.fantrax.com/fantasy/league/*
// @match        https://fantrax.com/fantasy/league/*
// @grant        GM_getValue
// @grant        GM_setValue
// @grant        GM_xmlhttpRequest
// @connect      127.0.0.1
// @run-at       document-start
// ==/UserScript==

`;

await mkdir(dirname(output), { recursive: true });
await writeFile(output, metadata + sources.join("\n"), "utf8");
console.log(`Built ${output}`);
