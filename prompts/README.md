# Stage prompts

One prompt per stage. Each is self-contained: paste it into Claude Code with
`SPEC.md` and `CLAUDE.md` in the repo. Each ends in a **gate** that must pass
before the next stage starts.

| # | Stage | Depends on | Status |
|---|---|---|---|
| 0 | Extract & measure | — | **ready** |
| 1 | Turn-expanded graph L(G) | 0 | **ready** |
| 2 | Time & capture model | 0, 1 | after Stage 0 numbers |
| 3 | Lower bound (DCPP relaxation) | 1, 2 | after Stage 0 numbers |
| 4 | Zoning | 2, 3 | after Stage 3 |
| 4c | Re-zone on measured overhead | 5 | **done** |
| 5 | Route solve + GPX | 4 | after Stage 4 |
| 6 | Coverage tracker & re-planner | 5 | **done** |
| 7 | Dashboard | 6 | after Stage 6 |

Stages 2–7 are deliberately unwritten. Their prompts depend on real measured
values — network size, tagging completeness, zone counts — that Stage 0 and
Stage 3 produce. Writing them now against estimates would violate the gating
principle the whole design rests on.

## What each prompt guarantees

- **Inputs** are named files, not assumptions.
- **Outputs** are named files, committed to `data/derived/` or `reports/`.
- **Gate** is a list of assertions that a test suite checks, not a judgement call.
- **Non-goals** are stated, so the stage does not creep into the next one.
