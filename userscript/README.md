# userscript/ — reserved

This directory is the home of the Tampermonkey bridge: XHR capture from Fantrax,
the in-page overlay for snake and auction drafts, the action executor, and
transport to the local backend.

**It is deliberately empty.** The bridge is owned by the `bridge` agent and
arrives in Phase 8 (capture and overlay) and Phase 10 (automation). Everything
in the write path is gated by an independent `safety` review — see
`docs/governance/gates.md`.

Phase 1 creates the directory so the monorepo layout in `docs/plan.md` is real,
and stops there. Do not add code here without the owning agent and its gate.
