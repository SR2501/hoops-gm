# Owner-only decisions

Agents may not decide these. **Escalate and stop** — do not proceed on an assumption, and do not implement "provisionally" while waiting.

---

## The list

### 1. Anything changing ToS exposure or the nature of Fantrax access

Read access via the official API and `fantraxapi` is settled (ADR-004). Writes go through the browser bridge as real interaction on the owner's own account.

Escalate if you are considering: direct programmatic writes to `/fxpa/req`, any access to a league the owner is not a member of, higher-frequency polling, or anything that would apply to accounts other than the owner's.

### 2. Enabling autonomous mode, or widening its scope caps

Autonomous execution is opt-in, per-session, and scope-capped (ADR-005). Turning it on for the first time, raising the round cap, extending it to a new action type, or lowering the confidence floor are all owner calls.

### 3. Any paid data subscription

Basketball Monster (~$9.95/mo), Hashtag Patreon, BALLDONTLIE All-Star ($9.99/mo), API-Sports Pro. The plan is built to work on free sources. Recommend if warranted, but do not sign up.

### 4. First action on a real draft or a live lineup lock

Rehearsal against mocks is agent work. The first time anything touches a real draft or a real lock is an owner decision, made deliberately and with the owner present.

### 5. Accepting an ADR

**Agents write ADRs as `Proposed`. Only the owner moves one to `Accepted`.** Never mark your own work accepted. This applies to ADR-001 through ADR-007 seeded at project start — they record decisions made in planning, but they are proposals until the owner says otherwise.

### 6. Anything sharing data or access with leaguemates

Multi-user support is planned (Phase 13), but who gets access, to what, and whether imported projection data may be exposed to another person are owner calls. Projection sources are personal-use only.

---

## Autonomous PR delivery — owner decision, 2026-08-18

Ordinary read-only and code PRs may be merged autonomously after every applicable
gate is green and an independent review approves. This authorizes delivery, not
owner-only decisions: any owner-only decision, unresolved `safety` veto, paid
service, ToS change, first live-account action, or ADR acceptance still requires
the agent to stop and escalate.

---

## How to escalate

1. Stop work on the affected item.
2. Append to `docs/handoff.md`: what you hit, what you would do, what the alternatives are, and what you need decided.
3. Mark the todo `blocked` with the reason.
4. Continue with unblocked work.

Do not batch several escalations into one vague question. One decision, clearly stated, with a recommendation.
