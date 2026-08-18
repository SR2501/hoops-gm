import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { readFile, readdir } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";
import test from "node:test";

const root = dirname(dirname(fileURLToPath(import.meta.url)));
const distPath = resolve(root, "dist", "hoops-gm.user.js");
const packageJsonPath = resolve(root, "package.json");
const packageLockPath = resolve(root, "package-lock.json");
const userscriptSourcePath = resolve(root, "src", "userscript.js");

async function build() {
  execFileSync(process.execPath, ["build.mjs"], { cwd: root, stdio: "pipe" });
  return readFile(distPath, "utf8");
}

test("build emits matching @updateURL/@downloadURL metadata pointing at the loopback backend", async () => {
  const output = await build();

  const updateUrlMatch = output.match(/^\/\/ @updateURL\s+(\S+)$/m);
  const downloadUrlMatch = output.match(/^\/\/ @downloadURL\s+(\S+)$/m);

  assert.ok(updateUrlMatch, "expected an @updateURL metadata line");
  assert.ok(downloadUrlMatch, "expected a @downloadURL metadata line");
  assert.equal(updateUrlMatch[1], downloadUrlMatch[1]);

  const url = new URL(updateUrlMatch[1]);
  assert.equal(url.protocol, "http:");
  assert.equal(url.hostname, "127.0.0.1");
  assert.equal(url.port, "8000");
  assert.equal(url.pathname, "/bridge/userscript.user.js");
  assert.match(output, /^\/\/ ==UserScript==/);
  assert.match(output, /\/\/ ==\/UserScript==\n\n/);
});

test("build metadata appears before any source code, and @updateURL comes after @version", async () => {
  const output = await build();

  const metadataEnd = output.indexOf("// ==/UserScript==");
  const updateUrlIndex = output.indexOf("// @updateURL");
  const versionIndex = output.indexOf("// @version");

  assert.ok(metadataEnd > 0, "expected a closing ==/UserScript== marker");
  assert.ok(versionIndex > -1 && versionIndex < metadataEnd);
  assert.ok(updateUrlIndex > versionIndex, "@updateURL must follow @version");
  assert.ok(updateUrlIndex < metadataEnd, "@updateURL must be inside the metadata block");
});

test("built version matches package.json and looks like a bumpable semver", async () => {
  const output = await build();
  const packageJson = JSON.parse(await readFile(packageJsonPath, "utf8"));
  const packageLock = JSON.parse(await readFile(packageLockPath, "utf8"));

  const versionMatch = output.match(/^\/\/ @version\s+(\S+)$/m);
  assert.ok(versionMatch, "expected an @version metadata line");
  assert.equal(versionMatch[1], packageJson.version);
  assert.equal(packageLock.version, packageJson.version);
  assert.equal(packageLock.packages[""].version, packageJson.version);
  assert.match(versionMatch[1], /^\d+\.\d+\.\d+$/);
});

test("build preserves the legacy script identity, storage key, and permission surface", async () => {
  const output = await build();
  const source = await readFile(userscriptSourcePath, "utf8");

  // @name + @namespace is the Tampermonkey identity inherited from 0.2.0.
  // Changing either can create a second script and orphan its GM storage.
  assert.match(output, /^\/\/ @name\s+hoops-gm bridge$/m);
  assert.match(
    output,
    /^\/\/ @namespace\s+https:\/\/github\.com\/SR2501\/hoops-gm$/m
  );
  assert.match(source, /const SECRET_KEY = "hoops-gm\.bridge-secret";/);

  // Widening any of these may make Tampermonkey require another permission
  // confirmation, defeating hands-off updates. A future intentional change
  // must update this contract and call that browser action out explicitly.
  assert.deepEqual(
    Array.from(output.matchAll(/^\/\/ @match\s+(\S+)$/gm), (match) => match[1]),
    [
      "https://www.fantrax.com/fantasy/league/*",
      "https://fantrax.com/fantasy/league/*",
    ]
  );
  assert.equal(
    Array.from(output.matchAll(/^\/\/ @noframes\s*$/gm)).length,
    1,
    "capture must install only in the top-level Fantrax document"
  );
  assert.deepEqual(
    Array.from(output.matchAll(/^\/\/ @grant\s+(\S+)$/gm), (match) => match[1]),
    [
      "GM_getValue",
      "GM_setValue",
      "GM_registerMenuCommand",
      "GM_addElement",
      "GM_xmlhttpRequest",
    ]
  );
  assert.deepEqual(
    Array.from(output.matchAll(/^\/\/ @connect\s+(\S+)$/gm), (match) => match[1]),
    ["127.0.0.1"]
  );
});

test("build never embeds a bridge-secret-shaped literal", async () => {
  const output = await build();
  const hasHexSecret = /[0-9a-f]{64}/i.test(output);
  const base64UrlRuns = output.match(/[A-Za-z0-9_-]{43,}/g) ?? [];
  const hasBase64UrlSecret = base64UrlRuns.some(
    (run) => /[A-Za-z]/.test(run) && /[0-9]/.test(run)
  );

  assert.ok(
    !hasHexSecret && !hasBase64UrlSecret,
    "no secret-shaped literal is embedded in the build"
  );
});

test("build output is a single file inside dist/, which stays gitignored", async () => {
  await build();
  const entries = await readdir(resolve(root, "dist"));
  assert.deepEqual(entries, ["hoops-gm.user.js"]);
});
