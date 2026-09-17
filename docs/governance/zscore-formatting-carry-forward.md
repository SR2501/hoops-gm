# Production z-score formatting-only delivery closure

Architect operational ruling, 13 September 2026. This is not an ADR acceptance,
an amendment to the experiment protocol or a new statistical experiment.

## Why this is separate

Independent adjudication
`zscore-final-adjudication-20260914T020704993399Z-e3f9ff9de3ce`
accepted the completed experiment and its limited descriptive evidence. It left
the Model gate open for the final-results addendum and the Code gate open:
Ruff 0.16.1 would format ten of thirteen checked Python files.

The evaluated bytes must remain recoverable. Formatting live files and then
claiming they are the original frozen candidate would be false. Repeating a
held-out evaluation merely to accommodate formatting is not authorized either.

## Ruling

Stage a **formatting-only delivery successor** in a new private directory.
The original freeze, source snapshots, packages, result, execution receipt,
independent adjudication and sixteen bound live files remain unchanged during
staging. The quant author prepares it; independent review approves or refuses
its equivalence. No agent approves its own successor.

The staging record must contain the actual creation time, formatter version,
explicit backend Ruff configuration and digest, complete argv, and a closed map
of all sixteen original/successor file identities. Only the thirteen Python
source/test files may pass through `ruff format`; the other three stay identical.
No lint auto-fix, manual edit, dependency change, new input, outcome reread,
recalculation, refit, metric change or second held-out run is allowed.

Every Python pair must have identical parsed ASTs with type comments retained
and location attributes excluded. Preserve a full diff as well: AST agreement
does not prove byte identity, source-inspection behavior, line numbers or
provenance hashes stayed the same. Any AST mismatch stops this path; do not
silently discard docstrings or ignore nodes to make it pass.

Independent review must confirm the complete file map, exact numerical-code
equivalence and the limits of that assertion. **Promotion is withheld until
that review and a separate coordinator instruction.** If approved, the same
formatter/configuration may produce those exact reviewed successor bytes in
the working tree, followed by the existing targeted Code gate. Unrelated API/UI
work must not be moved underneath its own review.

## What evidence may carry forward

Only the accepted evidence for the unchanged deterministic numerical method.
The original result continues to name the original freeze and original bytes;
no historical record is rewritten to point at the successor, and no new
pre-registration is claimed. The final-results addendum records the post-unblind
delivery transformation and, after independent approval, its equivalence record.

The successor is not permission to alter model behavior. Byte-checking forecast
and evaluation tools may correctly reject the old invocation against new live
bytes; it must not be rerun or its receipts rewritten to make that check pass.
Current-vendor calibration, availability adjustment, expected games, dollars and
strategy optimization remain unestablished.

## Rejected

Silently formatting the frozen candidate; downgrading the formatter; waiving
the Code gate; tuning or rerunning the held-out study; and relabelling a changed
artifact as pre-registered. If the difference is not demonstrably formatting
only, this delivery path stops and a new explicit disposition is required.
