import { mkdir, readFile, writeFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const root = dirname(fileURLToPath(import.meta.url));
const source = await readFile(resolve(root, "src", "userscript.js"), "utf8");
const output = resolve(root, "dist", "hoops-gm.user.js");

const metadata = `// ==UserScript==
// @name         hoops-gm bridge
// @namespace    https://github.com/SR2501/hoops-gm
// @version      0.1.0
// @description  Local-only transport foundation for the hoops-gm Fantrax bridge
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
await writeFile(output, metadata + source, "utf8");
console.log(`Built ${output}`);
