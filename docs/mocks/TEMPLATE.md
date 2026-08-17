# Mock — YYYY-MM-DD — <site>

## Configuration

**Mandatory.** Without this the prices cannot be normalised (R39) and the mock is unusable as AAV evidence.

| Field | Value |
|---|---|
| Site | |
| Date | |
| Format | auction / snake |
| Teams | |
| Budget per team | $ |
| Roster spots | |
| Starting slots | e.g. PG, SG, G, SF, PF, F, C, UTIL |
| Bench slots | |
| IR slots | |
| Scoring | 9-cat / points / other |
| Categories | if not standard 9-cat |
| My draft position / nomination order | |

## Tool usage

**Critical for calibration (R38).** A mock where our own values drove bidding is contaminated evidence and must be weighted separately.

- [ ] **Blind** — tool not used, did not exist, or deliberately not consulted
- [ ] **Partial** — consulted for some decisions (note which below)
- [ ] **Instrumented** — our values drove bidding

Notes:

## List used

| Field | Value |
|---|---|
| List identifier | e.g. `list-C`, or `none` |
| Open during bidding? | yes / partly / no |
| How much consulted | constantly / at decisions / glanced / ignored |

> Don't guess whether it was perturbed. If you know, the measurement is worthless.

## Adherence — one row per roster spot

"Followed" = took the list's top available recommendation at that moment.

| # | Player | Paid | List rank | Followed? | If not, why |
|---|---|---|---|---|---|
| 1 | | $ | | Y / N | |

Deviation reasons: be specific. "Gut" is honest and valid. So is "saw an injury note", "panicked on budget", "list looked wrong". This column separates bias from real information.

## Engagement level

Affects how much the clearing prices can be trusted.

- [ ] High — most managers active throughout
- [ ] Mixed — some autodraft or disengagement, especially late
- [ ] Low — significant autodraft or abandonment

Notes:

## Results

Every player, price paid, and drafting team. Paste the site's results export, a table, or a screenshot transcription — whatever is fastest. Completeness matters more than format; the importer handles the parsing.

```
player, price, team
```

## My roster

| Player | Paid | Notes |
|---|---|---|
| | $ | |

**Budget left at end:** $
**Roster shape:** stars-and-scrubs / balanced / accidental

## Behavioural notes

Honest self-observation. The point is to find tendencies worth flagging later, so unflattering entries are the useful ones.

- **Where did I overpay, and why?**
- **Where did I get a bargain?**
- **Did I panic, chase, or freeze at any point?**
- **Did I run out of budget early or finish with money unspent?**
- **Any category I neglected until it was too late?**

## "I wish I knew X right now"

**The most valuable section.** Every moment during the auction where information was missing. These are overlay requirements discovered under real time pressure rather than imagined at a desk.

-
-
-

## Inflation observations

- Did the early tier go over or under expectation?
- Did prices deflate later, and roughly when?
- Any player who went far above or below what seemed reasonable?

## Anything surprising

Rule quirks, UI behaviour, nomination dynamics, anything that would change how the overlay or the engine should work.
