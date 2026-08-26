// ESLint for `scripts/`, which no gate has ever covered.
//
// **Why this file exists.** `browser_probe.mjs` and `reliability_probe.js` are
// the only JavaScript in this repository outside `frontend/` and `userscript/`,
// and `ci.yml`'s frontend job runs `eslint .` with `working-directory:
// frontend`. Python in `scripts/` is at least type-checked by
// `backend/pyproject.toml`; these two were checked by nothing at all.
//
// **Why not just point the frontend job at `../scripts`.** Two reasons, both
// checkable. ESLint's flat config resolves `files` patterns relative to the
// config's base directory, so linting `../scripts` from `frontend/` puts the
// targets outside the base path. And `frontend/eslint.config.js` is a React
// config — `react-hooks` and `react-refresh` — which is the wrong rule set for
// a Node CLI and the wrong one again for a page-injected probe.
//
// **Why no imports.** `scripts/` has no `package.json` and no `node_modules`,
// so `import js from '@eslint/js'` is unresolvable from here: Node would walk
// `scripts/` -> repo root and find nothing. Reaching into
// `../frontend/node_modules` would make this config depend on the frontend's
// install layout. Core rules need no plugin, so this config imports nothing and
// enumerates the rules it wants. The cost is that `js.configs.recommended` is
// not inherited; the benefit is that the config cannot break when a sibling
// package's dependencies move.
//
// **Two environments, because these are genuinely different kinds of file.**
// `browser_probe.mjs` is a Node ES module that drives Chrome over CDP.
// `reliability_probe.js` is a payload *injected into a page* and evaluated in
// the browser — it is not a module, it never runs under Node, and it has no
// access to `process`. Linting both against one environment would either
// declare browser globals to a Node script or `process` to a browser payload,
// and `no-undef` is the rule that would then stop meaning anything.

const NODE_GLOBALS = {
  console: 'readonly',
  process: 'readonly',
  URL: 'readonly',
  // Node has had a global `WebSocket` since 22, which is `NODE_VERSION` in
  // `ci.yml`. `browser_probe.mjs` speaks CDP over one. Listed rather than
  // assumed: `no-undef` reported it the first time this config ran, which is
  // the check doing its job before anybody trusted its silence.
  WebSocket: 'readonly',
  TextDecoder: 'readonly',
  TextEncoder: 'readonly',
  setTimeout: 'readonly',
  clearTimeout: 'readonly',
  setInterval: 'readonly',
  clearInterval: 'readonly',
  fetch: 'readonly',
}

const BROWSER_GLOBALS = {
  document: 'readonly',
  window: 'readonly',
  fetch: 'readonly',
  console: 'readonly',
  setTimeout: 'readonly',
  clearTimeout: 'readonly',
  getComputedStyle: 'readonly',
  location: 'readonly',
}

// Deliberately a short list rather than a preset. Every rule here is one this
// repository has an argument for; `no-unused-vars` in particular is the one that
// catches a probe field computed and then never put into the payload, which is
// the JavaScript form of the "a field no assertion reads is decoration" rule the
// calibration lane arrived at from the other side.
const CORE_RULES = {
  'no-unused-vars': ['error', { argsIgnorePattern: '^_' }],
  'no-undef': 'error',
  'no-const-assign': 'error',
  'no-dupe-keys': 'error',
  'no-dupe-args': 'error',
  'no-duplicate-case': 'error',
  'no-unreachable': 'error',
  'no-fallthrough': 'error',
  'no-self-compare': 'error',
  'no-unsafe-negation': 'error',
  'no-cond-assign': 'error',
  'valid-typeof': 'error',
  'use-isnan': 'error',
  eqeqeq: 'error',
}

export default [
  {
    // The Node side: this file and the CDP driver.
    files: ['**/*.mjs', 'eslint.config.js'],
    languageOptions: {
      ecmaVersion: 2023,
      sourceType: 'module',
      globals: NODE_GLOBALS,
    },
    rules: CORE_RULES,
  },
  {
    // The browser side: payloads evaluated inside a page, never under Node.
    files: ['reliability_probe.js'],
    languageOptions: {
      ecmaVersion: 2023,
      sourceType: 'script',
      globals: BROWSER_GLOBALS,
    },
    rules: CORE_RULES,
  },
]
