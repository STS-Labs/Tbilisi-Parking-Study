# Stage 1 — Build the turn-expanded graph L(G)

Read `SPEC.md` §3.3 and §3.4, and `CLAUDE.md`. Stage 0's gate must have passed.

## Purpose

Make every route **legal and physically drivable by construction**, rather than
legal by later inspection. From this stage on, all routing happens in L(G).

## Inputs

- `data/derived/network.gpkg` (layer `arcs`) from Stage 0
- `data/raw/georgia-latest.osm.pbf` — for `type=restriction` relations

## Tasks

### 1. Parse turn restrictions
Extract every `type=restriction` relation intersecting the network, including:

- simple node-via restrictions (`no_left_turn`, `no_right_turn`, `no_u_turn`,
  `no_straight_on`)
- `only_*` restrictions, which forbid every manoeuvre except the named one
- **via-way restrictions** (via is a way, not a node) — these are commonly skipped
  by naive implementations and are exactly the ones that produce illegal routes
- conditional restrictions (`restriction:conditional`) — log them; apply only the
  unconditional part unless the condition covers the whole 09:00–18:00 shift

Anything unparseable is logged with the relation ID and the reason. Never dropped
silently.

### 2. Construct L(G)
- Node of L = one directed arc.
- Edge of L = one legal manoeuvre `a → b` where `head(a) == tail(b)`.
- Classify each manoeuvre as straight / right / left / u-turn from the bearing
  delta between the arcs' terminal segments.
- Edge cost = traversal time of `b` + turn penalty by class (SPEC §3.3).

### 3. U-turn policy
U-turn edges `a → reverse(a)` exist **only** where:
- the node is a dead-end tip, **or**
- carriageway width permits and no `no_u_turn` restriction applies.

Elsewhere the edge is **absent**, not penalised. Motorway and trunk arcs carry no
U-turn edges and are enterable only via `*_link` ramps.

### 4. Audit connectivity of L
Compute SCCs **of L**, not of the base network. This is the critical check: an arc
can be present and reachable in the base graph yet be a legal trap in L — enterable
but not leavable once turn restrictions apply.

## Outputs

- `data/derived/turn_graph.pkl` (or a sparse-matrix equivalent if size demands)
- `reports/01-turn-audit.md`
- `reports/01-turn-graph.html` — map highlighting traps, restricted junctions and
  permitted U-turn locations

### The report must contain

1. `|nodes|`, `|edges|` of L, and mean out-degree.
2. Restrictions: found / parsed / applied / unparseable, split by type, with the
   via-way count called out separately.
3. U-turn edges created, split by reason (dead-end tip vs width-permitted).
4. **Traps:** arcs with zero legal out-edges, or zero legal in-edges. List them all.
5. SCC analysis of L: largest component as a share of required traversal km, and
   every excluded arc with its cause.
6. How many required arcs from Stage 0 became unreachable once restrictions were
   applied — with an explicit note that under SPEC §1.1 these must be *resolved*,
   not dropped.

## Gate — tests must assert

- **Invariant U1:** for a sample of 1,000 random paths through L, every
  consecutive arc pair shares a node and violates no restriction.
- No edge exists in L that a parsed restriction forbids (direct adversarial test:
  for each parsed restriction, assert the forbidden edge is absent).
- No U-turn edge exists at a node failing the §3.3 U-turn conditions.
- L's largest SCC covers ≥ 99% of required traversal km — **if not, stop and
  report the exceptions individually.** Under "accuracy over everything", an
  unreachable required arc is a problem to solve, not a rounding error.
- **Manual spot-check:** pick 20 junctions in Tbilisi with known restrictions
  (one-way couplets in the centre, the Heroes' Square interchange, riverside
  embankment junctions). Verify each against satellite/street imagery and record
  the result in the report as a table. Automated tests cannot catch a restriction
  that OSM simply does not have.

## Non-goals

No coverage solving. No zoning. No lower bound. Build the graph, prove it legal,
report what is broken.
