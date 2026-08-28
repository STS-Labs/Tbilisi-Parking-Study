# Three ways to cover Zone B, and what each one costs

> **Zone A was requested and is not in the data.** `data/custom/B Zone_Streets/AB_zones.shp`
> holds one polygon, `Name = "Zone B"`, despite the layer being called `AB_zones`; its
> `FolderPath` names `Tbilisi Possible parking zones.kmz` as the source, so Zone A
> presumably exists there and was never exported. **Everything below covers Zone B
> only.** No Zone A boundary has been inferred or approximated, and nothing here is
> an A+B result.

Three complete pipeline runs over the same 24.0 km² zone, the same depot, the same
9 h shift, the same speed and turn models, the same pinned sizing constant. The only
thing that changes between them is **what counts as required**.

| Run | Required set | Output root |
| --- | --- | --- |
| Variant C | Everything OSM has inside Zone B, minus `highway=service` | `CUSTOM-OUTPUT/` |
| Run 1 — OSM full | Everything OSM has inside Zone B, service included | `RUN-OSM-FULL/` |
| Run 2 — customer net | Exactly the streets in the customer's `Streets.shp` | `RUN-CUSTOMER-NET/` |

---

## 1. The numbers

|  | Variant C | Run 1: OSM full | Run 2: customer net |
| --- | ---: | ---: | ---: |
| Required traversal | 390.9 km | 674.4 km | 445.5 km |
| Required centreline | 339.0 km | 622.3 km | 393.1 km |
| Required share of the drivable clip | 37.3% | 39.6% | **24.9%** |
| **Driving days** | **7** | **21** | **13** |
| Dates | 2026-08-28 → 09-03 | 2026-08-29 → 09-18 | 2026-08-29 → 09-10 |
| **Total driving** | **35.5 h** | **100.8 h** | **71.4 h** |
|   capture | 13.5 h | 29.8 h | 16.6 h |
|   deadhead | 13.8 h | 33.8 h | 29.0 h |
|   turns | 8.2 h | 37.1 h | 25.9 h |
|   of which depot legs | 1.8 h (5.0%) | 6.1 h (6.0%) | 3.3 h (4.6%) |
| Deadhead as % of capture | 102% | 113% | **174%** |
| Turns as % of driving | 23% | **37%** | 36% |
| **Hours per required km** | **0.0908** | **0.1495** | **0.1604** |
| Required km per driving day | 55.8 | 32.1 | 34.3 |
| Stage 3 bracket | 23.3 – 31.0 h | 54.4 – 88.0 h | 40.6 – 63.0 h |
| Stage 5 gap over the lower bound | 116% | 116% | 213% |
| Required length never covered | 3.5 km (0.9%) | 22.1 km (3.3%) | 5.5 km (1.2%) |
|   of which unreachable by any tour | 3.4 km | 22.0 km | 5.4 km |
|   of which reachable and simply missed | 0.073 km | 0.073 km | 0.073 km |

**Every run misses the same three reachable arcs, 73 metres in total.** That is the
known tail from the Zone B campaign — arcs of 2.6 m, 12.0 m and 19.2 m — and it does
not move with the scope. Everything else uncovered is unreachable by construction,
and *how much* is unreachable turns out to be one of the findings (§2).

### The row the customer actually reads

Everything above is measured against each run's own idea of what it should cover,
which makes the three incomparable. This is not: it is the customer's own 347.0 km of
linework, and how much of it each plan puts under the camera — length within 15 m of
an arc the plan drives **in capture mode**, not merely of an arc it lists as required.

|  | Variant C | Run 1: OSM full | Run 2: customer net |
| --- | ---: | ---: | ---: |
| Customer layer supplied | 347.0 km | 347.0 km | 347.0 km |
| **Filmed** | **336.6 km (97.01%)** | 337.5 km (97.27%) | **343.2 km (98.90%)** |
| Not filmed | 10.4 km | 9.5 km | **3.8 km** |
| Centreline actually filmed | 335.5 km | **600.2 km** | 387.7 km |
| Total driving | **35.5 h** | 100.8 h | 71.4 h |
| Driving days | **7** | 21 | 13 |

Read those two rows together. **Run 1 films 600 km of street to deliver 0.9 km more
of the customer's layer than variant C does** — 79% more filming, 184% more driving,
for a quarter of a percentage point. It is the most expensive way to answer the
question and very nearly the least effective.

*(The 97.01% reproduces the committed Zone B campaign's published 97.0% / 336.6 km
reconciliation from an independent measurement, which is the check that this table is
measuring what it says it is.)*

---

## 2. What does including service roads actually buy?

Run 1 against variant C:

| | |
| --- | ---: |
| Extra required traversal | **+283.4 km** (+72.5%) |
| Of which no legal tour can reach | −18.6 km |
| Extra coverage actually delivered | +264.8 km |
| Extra driving | **+65.3 h** (+184%) |
| Extra driving days | **+14** (+200%) |
| Marginal cost of the extra kilometre | **0.247 h/km** |
| Cost of a variant C kilometre | 0.091 h/km |
| **Extra of the customer's layer delivered** | **+0.9 km** |

**The marginal kilometre costs 2.7 times the average one, and it is not worth the
marginal day.** Fourteen extra days buy 265 km of driveways, parking aisles and yard
roads — 18.9 km per day against variant C's 55.8. If the customer is paying by the
day, service roads roughly triple the bill.

**The cost is turns, not kilometres.** Capture time rises 16.3 h; turn time rises
**28.9 h**, to 37% of all driving — the largest single term in Run 1's day. A
`highway=service` spur is a dead end: drive in, U-turn at 20 s, drive out. Every
metre is filmed once and driven twice, and the manoeuvre at the tip costs more than
the street. That is topology, exactly as the brief predicted, and not a regression —
but it is far more expensive than the kilometre count suggests.

**22.0 km of what variant A requires cannot be driven at all.** Orphan service
components — a car park reachable only through a barrier, a yard behind a gate — are
required by the scope rule and unreachable by any legal tour. Variant C strands
3.4 km; variant A strands 22.0. Widening the scope adds 18.6 km of coverage that
exists only on paper, and a plan that promises it is promising what it cannot deliver.

**So: include service roads only if the customer specifically wants driveways and
parking aisles filmed, and price them separately.** They do not behave like streets
and folding them into a blended rate will misprice every future job.

---

## 3. Does the customer's network cost more or less per km than OSM's?

**More. It is the most expensive of the three, per required kilometre.**

| | Variant C | Run 1 | Run 2 |
| --- | ---: | ---: | ---: |
| Hours per required km | 0.0908 | 0.1495 | **0.1604** |
| Deadhead as % of capture | 102% | 113% | **174%** |
| Measured intra-zone overhead (p75) | 2.73 | 3.41 | **4.49** |
| Required share of the drivable network | 37.3% | 39.6% | **24.9%** |

Run 2 requires **less** road than Run 1 — 445.5 km against 674.4 km — and still costs
more per kilometre. Against variant C it requires 14% more traversal for **101% more
driving**.

The reason is the last row. The customer's layer is a *list of streets*, not a
*region*: it is 24.9% of the drivable network the car has to cross, against variant
C's 37.3%. Between any two required streets the car drives roads nobody is paying it
to film, and it does that for 29.0 of its 71.4 hours.

> **Cost per kilometre is set by the density of the required set inside the network
> that connects it, not by its size.** A large contiguous job is cheap per kilometre.
> A small scattered one is expensive, and the more selective the customer's list, the
> worse it gets.

Run 1's penalty is turns; Run 2's is deadhead. They arrive at nearly the same place —
about 0.15 h per required km — from opposite directions. Variant C is cheap because
it is both contiguous **and** free of dead ends.

---

## 4. Which run would you quote a customer for?

**Variant C, and it is not close.** Two of the three comparisons are dominations
rather than trade-offs.

| Against variant C | Extra of the customer's layer filmed | Extra driving | Cost per extra customer km |
| --- | ---: | ---: | ---: |
| Run 1 — OSM full | +0.9 km | +65.3 h | **72.8 h/km** |
| Run 2 — customer net | +6.5 km | +36.0 h | **5.5 h/km** |

And between the two new runs, **Run 2 dominates Run 1 outright** on this customer's
own specification: it films 5.6 km *more* of their layer in 29.4 h *fewer* and eight
days sooner. If the customer's `Streets.shp` is the contract, Run 1 is not a
more-thorough option, it is a worse one.

That leaves variant C against Run 2, which is a genuine trade at a knowable price:

| | Variant C | Run 2 |
| --- | ---: | ---: |
| Of the customer's 347.0 km | 336.6 km — **97.0%** | 343.2 km — **98.9%** |
| Driving days | **7** | 13 |
| Total driving | **35.5 h** | 71.4 h |
| Centreline filmed | 335.5 km | 387.7 km |

**Doing exactly what the customer asked costs twice what doing a superset of it
costs.** Run 2 films 52 km more centreline than variant C and gains 6.5 km of the
customer's layer for it — 5.5 hours per kilometre, against the 0.09 h/km the first
336 km cost. Nobody should pay that, and nobody should quote it.

The reason is §3: the customer's list omits the streets that lie *between* the
streets it includes, the car drives them anyway, and it drives them uncompensated.
Variant C films those same connecting streets and gets paid for them.

### The quote

**Variant C, priced by the day, with the residual handled by hand.**

1. **The 10.4 km of the customer's layer variant C does not film.** Do not solve it
   with a second campaign at 5.5 h/km. It is 80 short pieces, every one listed with a
   location and a reason in `RUN-CUSTOMER-NET/surveys/unverified-streets.md`, and
   §5 shows most of them are building sites and gated roads that a driver may not be
   able to enter in the first place. A morning of survey settles what is real; only
   then is it worth routing.
2. **`highway=service`, if asked for at all, quoted separately** at roughly 0.25 h
   per kilometre — nearly three times the street rate — with 22 km of it declared
   undeliverable up front.

**And what prices the job is the day, not the kilometre.** The three runs land
between 32 and 56 required km per driving day, and the spread is governed entirely by
how contiguous the required set is. Ask a new customer for a **region**, not a list
of streets: the same car covers roughly 70% more road per day, and the customer gets
more of their own list filmed for less money.

---

## 5. "10.3 km not in OSM" was the wrong conclusion, and the right one is cheaper to fix

The brief for Run 2 predicted 127 parts and 10.3 km of the customer's layer that OSM
does not have, clustered around 44.795–44.800 E / 41.695–41.701 N, and suggested that
adding them to OSM would fix it permanently for every future run. Building the run
measured something different.

**Every metre of the customer's layer has an OSM way underneath it.** Matched against
the whole arc table, coverage is 100.00%. The pieces that come out unmatched are the
ones whose OSM counterpart the **drivability filter** removed, and the reason it
removed them is the useful part:

| OSM says | streets | What that means |
| --- | ---: | --- |
| `highway=construction` | 51 | OSM knows the street; it is being built |
| `access=private` | 11 | OSM knows the street; there is a gate |
| `barrier` blocks the way | 6 | OSM knows the street; there is a bollard |
| `footway` / `steps` | 11 | The customer digitised something that is not a road |
| `access=no` | 1 | OSM knows the street; entry is signed off |

The predicted cluster is real — the `construction` group sits exactly where the brief
said it would — but its cause is the opposite of what was assumed. **OSM has caught
up with that development already** and is telling us the roads are not finished.
Adding them to OSM would achieve nothing; they are there. What is worth doing is
*retagging* the ones that have since been built — a smaller, more precise job, and
exactly what the survey asks the driver to establish.

**The layer is not an independent source either.** 99.2% of `Streets.shp`'s vertices
sit under a **millimetre** from an OSM node; the median distance is 46 micrometres.
It is an OSM extract filtered to real streets, which is why it resembles variant C
(347.0 km against 390.9) and why it agrees with OSM so precisely. That does not make
it less useful — it is a perfectly good statement of what the customer wants filmed —
but it is not corroboration, and a reconciliation between the two is not the
independent check it appears to be.

How much of the layer is "missing" depends entirely on what it is compared to, and
all five of these are true:

| Compared against | Covered | Uncovered |
| --- | ---: | ---: |
| Variant C's network inside Zone B | 340.2 km (98.03%) | 6.8 km |
| The same, service included | 341.7 km (98.48%) | 5.3 km |
| Every drivable arc in the clip, no service | 340.9 km (98.23%) | 6.1 km |
| **Every drivable arc in the clip** (the basis Run 2 uses) | **342.3 km (98.65%)** | **4.7 km** |
| Every arc in the table, undrivable included | 347.0 km (100.00%) | 0.0 km |

Run 2 uses the fourth, because the question it has to answer is *can the routing
network carry this street* — and an arc the filter excluded cannot carry anything.
Quoting any of the others without saying which is how "3.0% not in OSM" became a
data-gap story instead of an access story.

---

## 6. The sizing constant is now the largest error in all three plans

Every run above was sized on `ZONE_OVERHEAD_MEASURED = 2.2598` — Tbilisi's p75,
transferred by instruction and pinned per CLAUDE.md. What each run actually drives:

| | Sized on | Measured p75 | Under-estimate | Zones split | Days planned → driven |
| --- | ---: | ---: | ---: | ---: | ---: |
| Tbilisi | 2.2598 | 2.2030 | −2.5% | 4 | 43 → 47 |
| Variant C | 2.2598 | 2.7297 | +20.8% | 3 | 4 → 7 |
| Run 1 | 2.2598 | 3.4081 | **+50.8%** | 12 | 9 → 21 |
| Run 2 | 2.2598 | 4.4927 | **+98.8%** | 8 | 5 → 13 |

Stage 4 sized Run 1 at 9 days and Run 2 at 5. Stage 5 drove them in 21 and 13,
because every zone overran its window and had to be split, and each split adds a
depot leg pair.

**The hours are sound; the day counts are inflated.** Run 1 drives 100.8 h — 12.2
productive days of content spread over 21 calendar days. Run 2 drives 71.4 h, 8.7
days of content over 13. Sections 2 to 4 compare on hours, which CLAUDE.md rule 3
names as the KPI, and hours move only by the extra depot legs the splits cost:
6.1 h and 3.3 h, under 6% of each total.

**It has not been fed back, and it must not be automatically.** CLAUDE.md is explicit
that a constant read by an early stage and measured by a later one does not converge,
and that changing it is a deliberate reviewed act. What these runs establish is new,
though: the constant **does not transfer across scopes**, not merely across cities.
The same zone, the same car and the same shift need 2.73, 3.41 or 4.49 depending only
on what is required inside it. Sizing on any single measured p75 will keep being
wrong. The honest fix is to size on a *predicted* overhead — a function of required
density and dead-end share, both of which Stage 0 already measures — and that is a
Stage 4 change deserving its own brief.

---

## 7. Reading these numbers

- All three runs are **Zone B only**. Zone A is absent from the data (top of this
  page) and nothing has been extrapolated to it.
- Variant C is the committed campaign under `CUSTOM-OUTPUT/`, re-read for this
  comparison and **not re-run**; its artifacts are byte-identical to what was
  committed.
- Runs 1 and 2 both start **2026-08-29**, pinned as a literal per CLAUDE.md rule 5.
- Run 2's routable network is variant A on purpose. The variant filter deletes arcs
  from the network, so running C would have let a scope decision made for a different
  campaign remove a street the customer explicitly asked for. Under A the filter drops
  nothing; the service roads it leaves in are routable-only and never required.
- Run 2 requires 393.1 km of OSM centreline to cover 347.0 km of customer linework.
  The 13% difference is divided carriageways and service parallels: where two OSM
  centrelines lie under one customer line, both are required, because filming one
  does not film the other. SPEC §1.1 resolves that toward coverage.
- Every figure is read from `data/derived/00-network-stats.json`, `03-bounds.json`,
  `04-zones.json`, `05-routes.json`, `05-routes.gpkg` and `00-custnet.json` in the
  three output roots. Nothing is estimated.
