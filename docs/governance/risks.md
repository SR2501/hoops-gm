# Risk register

Live document. Add rows as risks emerge; update status as they are mitigated or realised. Do not delete a realised risk — record what happened.

Severity: 🔴 high · 🟡 medium · 🟢 low

---

## Upstream & integration

| ID | Risk | Sev | Mitigation | Owner |
|---|---|---|---|---|
| R1 | Fantrax changes `/fxpa/req` schema without notice | 🟡 | Pin `fantraxapi`; contract tests with recorded fixtures; raw `bridge_payloads` retained for replay | `data-engineer` |
| R2 | `FANTRAXUSER` cookie expires mid-season or mid-draft | 🟡 | Encrypted storage, expiry detection, re-login flow; **verify freshness before any draft or lock** | `data-engineer` |
| R3 | `stats.nba.com` IP block from over-polling | 🟡 | ~1 req/s throttle, backoff, caching; live data from `cdn.nba.com` instead | `data-engineer` |
| R4 | `nba_api` breaks on an NBA-side change mid-season | 🟡 | Contract tests catch it; BALLDONTLIE All-Star as costed fallback (owner decision) | `data-engineer` |
| R5 | Fantrax adds bot detection or CSRF to internal endpoints | 🟡 | Read path degrades to bridge capture; write path is browser-native and less exposed | `bridge` |
| R6 | Projection sources change CSV format between seasons | 🟢 | Per-source column-mapping profiles, validation on import, unmatched report | `quant` |

## Model & correctness

| ID | Risk | Sev | Mitigation | Owner |
|---|---|---|---|---|
| R7 | **Player identity mismatch silently corrupts every downstream number** | 🔴 | Anchor on Fantrax `getPlayerIds` + `nba_api`; confidence scoring; unmatched report; manual override; dedicated test suite | `data-engineer` |
| R8 | Availability model is overconfident — poorly calibrated `p(play)` | 🔴 | Model gate requires calibration reporting, not accuracy alone; held-out backtest | `quant` |
| R9 | Percentage categories modelled as raw pct instead of volume-weighted impact | 🔴 | Explicit test cases: low-volume high-pct players must not rank highly | `quant` |
| R10 | DNP reason codes are inconsistent; "rest" laundered as minor ailment | 🟡 | Normalization layer; model leans on observed patterns over stated reasons | `quant` |
| R11 | Availability model trained on stale regime — league behaviour shifts season to season | 🟡 | Recency weighting; re-evaluate calibration in-season | `quant` |
| R12 | Auction inflation model wrong under live conditions, never tested at speed | 🟡 | Validate against the mock corpus before the real draft | `quant` |
| R13 | Overfitting to a small mock corpus when calibrating opponents | 🟢 | 10+ mocks minimum; treat opponent models as priors, not truth | `quant` |

## Automation & account

| ID | Risk | Sev | Mitigation | Owner |
|---|---|---|---|---|
| R14 | **Automation bug submits a wrong pick or an illegal lineup** | 🔴 | Full guardrail set; dry-run default; validity precheck; independent `safety` sign-off | `safety` |
| R15 | Auto-set fires on stale injury data | 🔴 | Availability freshness check — escalate rather than act on stale reports | `safety` |
| R16 | ToS exposure from write automation | 🟡 | Supervised default; owner's own account only; owner-only decision to enable autonomous | owner |
| R17 | Bridge secret leaks, exposing the local action queue | 🟢 | Locally generated secret, `127.0.0.1` binding, secret never committed | `bridge` |

## Schedule & delivery

| ID | Risk | Sev | Mitigation | Owner |
|---|---|---|---|---|
| R18 | **Draft day does not move; spine incomplete by then** | 🔴 | Spine-first sequencing; phases 0–5, 8, 9 are the deadline set | `architect` |
| R19 | Draft format unconfirmed — auction vs snake | 🟡 | Both built as first-class; confirm with commissioner early | owner |
| R20 | Chrome throttles background tabs, stalling draft polling | 🟡 | Fantrax must be visible and active during a draft; documented in the runbook | `bridge` |
| R21 | Scope growth crowds out rehearsal time | 🟡 | Rehearsal is a deliverable, not a buffer; 10+ mocks are scheduled work | `architect` |
| R22 | Governance overhead exceeds its value for a solo project | 🟢 | `architect` owns the call to cut it; four gates and seven agents is the deliberate floor | `architect` |

## Realised

*(none yet — record here with date and outcome when one lands)*
