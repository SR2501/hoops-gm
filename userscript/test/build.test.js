import assert from "node:assert/strict";
import { execFile } from "node:child_process";
import { readFile } from "node:fs/promises";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { promisify } from "node:util";
import test from "node:test";

const execFileAsync = promisify(execFile);
const root = fileURLToPath(new URL("..", import.meta.url));

test("build metadata carries the loopback update/download URL and version", async () => {
  // Run the real build script: this exercises the exact code path
  // Tampermonkey relies on, rather than a second, drifting copy of the
  // metadata block. It writes to the same dist/ the developer workflow
  // uses (gitignored, safe to regenerate).
  await execFileAsync(process.execPath, ["build.mjs"], { cwd: root });

  const built = await readFile(join(root, "dist", "hoops-gm.user.js"), "utf8");
  const packageJson = JSON.parse(await readFile(join(root, "package.json"), "utf8"));

  assert.match(built, /^\/\/ ==UserScript==/);
  assert.match(built, /\/\/ ==\/UserScript==\n\n/);
  assert.match(
    built,
    new RegExp(`// @version\\s+${packageJson.version.replace(/\./g, "\\.")}\\b`)
  );

  const updateUrlMatch = built.match(/\/\/ @updateURL\s+(\S+)/);
  const downloadUrlMatch = built.match(/\/\/ @downloadURL\s+(\S+)/);
  assert.ok(updateUrlMatch, "@updateURL is present");
  assert.ok(downloadUrlMatch, "@downloadURL is present");
  assert.equal(updateUrlMatch[1], "http://127.0.0.1:8000/bridge/userscript.user.js");
  assert.equal(downloadUrlMatch[1], "http://127.0.0.1:8000/bridge/userscript.user.js");
  // Tampermonkey's own updater will not treat http://localhost or an IP
  // literal other than the loopback address as the same origin the backend
  // actually serves from (ADR-001): both URLs must be identical and
  // loopback, never a hostname that could resolve off-machine.
  assert.equal(updateUrlMatch[1], downloadUrlMatch[1]);
  assert.match(updateUrlMatch[1], /^http:\/\/127\.0\.0\.1:8000\//);

  // ADR-010: no bridge secret is ever baked into a build. There is no
  // legitimate reason for a full hex-64 or base64url-43 secret-shaped
  // literal (the two accepted stored-secret shapes) to appear anywhere in
  // the built output; the source only ever references the storage *key
  // name*, never a value matching those shapes. Checked in JS rather than
  // one dense regex so an ordinary comment divider of dashes (which matches
  // the character class but is not secret-shaped: no digits, no mixed case)
  // cannot false-positive.
  const hasHexSecret = /[0-9a-f]{64}/i.test(built);
  const base64UrlRuns = built.match(/[A-Za-z0-9_-]{43,}/g) ?? [];
  const hasBase64UrlSecret = base64UrlRuns.some(
    (run) => /[A-Za-z]/.test(run) && /[0-9]/.test(run)
  );
  assert.ok(
    !hasHexSecret && !hasBase64UrlSecret,
    "no secret-shaped literal is embedded in the build"
  );
});
