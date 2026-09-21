# How the Tbilisi capture routes were built

*Methodology note — 26 August 2026*

---

## What this document is for

This accompanies the fifty day-routes in `reports/05-routes/`. It explains how they
were produced, what we assumed along the way, and — the part that matters most —
how far we can and cannot vouch for them.

We have tried to write it so that two different readers get what they need. If you
are scheduling the campaign, sections 1, 7 and 8 are the ones that bear on your
decisions. If you are going to audit the work, section 10 tells you how to
reproduce and check every number here.

One thing to say plainly at the outset, because it shapes everything below. **These
routes are not proven optimal, and we would be misleading you if we said they
were.** What we can say is narrower and, we think, more useful: within a set of
choices we made explicitly, the routing is solved exactly, and where it is not
exact we have measured the size of the gap rather than waving at it. Section 7
sets out precisely where the line falls.

---

## 1. The problem, stated properly

A single camera car has to drive every drivable street in Tbilisi so that the
stereo rig captures usable footage of both sides. It works from one depot on the
western edge of the city, inside a fixed daily shift, and it has to finish before
the light goes in the autumn.

That is a harder problem than it sounds, for four reasons that turned out to drive
everything:

**Capture is directional, and sometimes needs repeating.** A narrow two-way street
can be captured in one pass from either direction. A wide one needs both
directions. A one-way street with more than three lanes needs *two passes in the
same direction*, in different lane groups — and on a one-way you cannot simply
reverse, so the second pass means driving a loop back round.

**Turning is constrained.** One-way systems, no-left-turn signs, and the fact that
you cannot U-turn wherever you like all mean that "these two streets touch" is not
the same as "you can get from one to the other". We had to model manoeuvres, not
just streets.

**Speed is capped where it counts.** Footage above 40 km/h is not usable, so every
required pass is slow. Repositioning between them is not capped, which makes
deadhead cheaper per kilometre than capture — a detail that turns out to matter in
several places.

**The depot is in the wrong place.** It sits about 8 km west-south-west of centre
while the city extends east. Every day pays to get out and back, inside the shift.

Formally this is a *generalised directed rural postman problem with arc
multiplicities on a turn-expanded graph, with vehicle capacity and a fixed depot*.
It is NP-hard, and no exact solution exists at city scale. The whole method below
is an answer to the question: given that, what can we actually guarantee?

---

## 2. How we worked

We built the thing in six stages, and we did not let a stage start until the
previous one had passed a gate — a set of automated assertions written, wherever
we managed it, *before* the code that had to satisfy them. There are 886 of these
tests now and they run in about three minutes. They are not decoration. Four times
in this project a gate caught something that looked completely convincing and was
wrong, and section 7 lists those cases because they are the best evidence we have
that the process works.

Three rules governed the work throughout, and they are worth stating because they
explain choices that would otherwise look strange.

**Accuracy first, efficiency second.** Where the data was ambiguous, we defaulted
to the more demanding requirement. If we could not tell whether a street needed one
pass or two, it got two. This makes the campaign longer and we did it anyway.

**No invented geometry.** Every coordinate in every output traces back to a node in
the source data. Nothing is smoothed, interpolated, or joined by a synthesised
connector.

**Everything is reported against a bound.** A route with no stated optimality gap
is an incomplete result. We would rather publish an uncomfortable gap than a bare
number.

And one rule about numbers: where something is estimated rather than measured, it
is labelled. We have tried to be consistent about this even where it is
unflattering.

---

## 3. Building the network

We started from the OpenStreetMap extract for Georgia, clipped to the Tbilisi
municipality boundary plus a 2 km buffer so that routes near the edge are not
artificially trapped.

From 286,036 directed arcs we kept 170,176 as drivable and required — motorways
through to residential streets and living streets, plus every slip road and ramp.
We dropped footways, steps, tracks, anything gated or private, and anything with a
surface a passenger car cannot manage. **Every drop is logged with a
machine-readable reason**; there is no unexplained loss anywhere in the pipeline.

Two judgements here are worth surfacing.

We took the largest strongly connected component and reported what fell out. About
2% of the network is in fragments that cannot be reached from the rest — mostly
hillside districts where OSM has not connected the streets. That is a data-quality
finding, not noise, and it is reported rather than absorbed.

We derived road gradient from a 30-metre elevation model, because only 46 arcs in
the whole city carry a tagged incline. This turned out to need care, and we come
back to it in section 5.

**The turn graph.** Rather than checking legality after routing, we built it in
from the start. We converted the street network into a graph whose *nodes* are
directed arcs and whose *edges* are legal manoeuvres — 166,693 nodes and 287,850
manoeuvres, with 1,466 OSM turn restrictions applied, including the awkward
via-way ones. U-turns exist only where they are physically possible: at dead ends,
and at junctions wide enough to make one. Motorways carry none and are enterable
only by ramp.

The consequence is that *any* path through this graph is a legally drivable
sequence. We do not have to check routes for legality afterwards, because an
illegal route cannot be expressed.

---

## 4. Turning kilometres into hours

A plan measured in kilometres is not a plan. Stage 2 built a speed model so we
could talk in hours.

The model is deliberately simple and deliberately *multiplicative*:

```
speed = base(road class, or the posted limit) × gradient × surface × width ÷ congestion
capture speed = min(speed, 40 km/h)   — except motorways and trunks, see below
```

Every term multiplies, which means the whole model is linear in log-speed. That is
not an aesthetic choice: it means the coefficients can be re-fitted from real GPS
traces later with one ordinary least-squares solve, rather than needing an
optimiser. We tested this by generating data from a known model and recovering it —
it comes back to eight decimal places.

The gradient term is anchored to a single figure in the specification: a 12% Tbilisi
lane runs at 12 km/h, not the 30 km/h a flat residential street manages. Solving
backwards from that one anchor fixes the whole term, so there is one gradient
assumption to argue with rather than four.

**We found a real problem with the elevation data and we want to flag it.** A 30 m
elevation model over a 39 m street segment produces a lot of spurious gradient. We
measured how much by looking at bridges and tunnels — flat by construction, so
whatever slope the model reports on them is close to pure error. Over 1,426 short
bridge and tunnel decks the median apparent height change was 0.52 m, which on a
short segment is a fake 4% grade. We subtract that noise floor before the gradient
term sees it. It removes about 10.6 hours from the campaign that were pure
measurement error. Without it we would have been modelling the elevation model's
noise and calling it Tbilisi's hills.

The 40 km/h cap turns out to matter less than you would expect, for a reason worth
knowing: it binds on only 388 km of the 5,725 km of required traversal. Most of
Tbilisi's streets are already slower than the camera needs.

---

## 5. Bounding the problem before solving it

Before producing any plan, we bracketed the answer from both sides. This is the
step that lets us say anything at all about quality later.

**The transform that makes it tractable.** Postman problems are defined over edges,
but our graph has coverage requirements on *nodes*. So we split every node in two —
an "arrive" node and a "depart" node — joined by an edge that carries the
requirement. Covering a street k times becomes traversing one specific edge k
times, which is an ordinary Chinese Postman problem with lower bounds, and *that*
is solved exactly by min-cost flow. This is the single most important structural
decision in the project. Trying to cover nodes directly is the standard way this
class of problem gets solved wrongly.

We split that edge in two, in fact: one priced at capture speed for the required
passes, one at the uncapped deadhead speed for any extra. That is what the
specification says about speed, and it means the solver charges a repeat pass
correctly without being told to.

**The upper bound** is a real, drivable, closed tour of the whole city. We fixed a
direction for every narrow two-way street, solved the resulting Chinese Postman
exactly, and extracted a single circuit. For the scope we ended up driving, that
tour is 272.0 hours.

**The lower bound** had to be computed separately, and this is where we corrected
the specification. The original document called the fixed-orientation tour a *lower*
bound. It is not — fixing a direction *adds* a constraint, so the result can only
be at or above the true optimum. It is a feasible solution, and feasible solutions
bound from above. We computed a genuine lower bound instead, from a linear
relaxation that lets each narrow street choose its own direction and drops
integrality: 178.6 hours.

That correction is not pedantry. Under the original wording, an invariant test
would have *rejected* any plan better than the tour — the test would have thrown
out exactly the improvements the later stages exist to find. The specification was
amended.

**What the bracket taught us.** The gap between 178.6 and 272.0 hours is wide, and
we decomposed it. Going from the relaxation to an integral solution with one fixed
orientation accounts for almost all of it; making that solution *connected* costs
1.8 hours, well under one per cent. In other words the routing itself is close to
exact for a given orientation, and the bound is loose because a linear relaxation
is allowed to cover half of one direction of a street and half of the other — a
fractional answer no car can drive.

That finding set the agenda for the rest of the project: **do not go looking for
savings in the routing. Go looking in the orientation.**

---

## 6. From one tour to fifty days

A single 272-hour circuit is not a plan. It has to become days.

**Zoning.** We partitioned the required network into zones of roughly one shift
each, weighted by capture time. Critically this is a *graph* partition, not a
geographic one — the river and the ridgelines mean two points 500 m apart can be
6 km apart by road, so clustering on the map produces days no driver can drive. We
required the partitioner to produce connected zones, and finished the balance with
a local search that only ever moves a segment across a zone boundary and never one
whose removal would split its zone.

We size zones on capture time but *days* are what has to fit, and a far zone with
the same capture time is a longer day. So each segment carries its share of the
depot leg its zone will pay, which makes distant zones automatically smaller.

**Depot legs, routed rather than estimated.** Earlier stages estimated depot legs
from straight-line distance bands. Stage 4 routed them properly over the manoeuvre
graph, and they came out about 13% shorter than the estimate — 28.0 hours across
the campaign rather than 32.2. The specification's worry that "eastern days lose up
to two hours to commuting" turns out to be true only of the eastern days; the
typical day spends about half an hour in total getting to work and home.

That correction had a consequence nobody expected. It reversed a scope decision:
a fuller variant of the network that had been ruled out as impossible was
re-measured and found to fit with a fortnight to spare. We report that in
`04b-recheck.md`; the decision to stay with the smaller scope was ultimately taken
on other grounds, deliberately and on the record.

**Sequencing: distant zones first.** This is counter-intuitive and worth
explaining. Early in the campaign the corridors leading out to the far districts
are still uncovered, so a long drive out can do useful work on the way. Late in the
campaign those same corridors are already done and the same drive is pure dead
time. So the far zones go first. It is easy to implement backwards, so the test
suite asserts the ordering directly.

It also bought something we did not plan for: because the long days end up at the
start of the campaign, they get driven while the days are longest. The plan
tolerates a later start than it otherwise would.

**Daylight.** We compute sunset for each day from the standard solar position
algorithm and cap the usable window at whichever comes first, sunset or the end of
the shift. Starting on 25 August, no day in this plan is daylight-limited — the
campaign finishes 13 October, when the sun still sets comfortably after the shift
ends. The plan could start as late as early October before that stops being true.

**Solving each day.** Each day is then its own routing problem: start at the depot,
cover that zone's streets, return to the depot. Deadhead is allowed over the
*entire* network, not just within the zone — restricting it to zone boundaries
produces worse routes and can make a zone unsolvable outright. Each day is solved
by the same exact min-cost-flow machinery as the whole-city tour.

---

## 7. What we can and cannot claim

This is the section to read if you are deciding how much to trust the output.

### What is proven

Every one of these is asserted by an automated test that re-derives the answer from
the published artifacts rather than trusting the solver's own account of itself:

- **Every required street is covered**, at least as many times as required, summed
  across the campaign. Every narrow two-way street is driven at least once.
- **Every manoeuvre in every day is legal.** Not "checked afterwards" — a route
  that turns where it may not turn cannot be expressed in our graph at all.
- **Every day starts and ends at the depot**, and closes as a genuine circuit.
- **No day exceeds its shift window**, counting capture, turns, repositioning, both
  depot legs and the break.
- **No required pass is scheduled above 40 km/h**, except on motorways and trunk
  roads, where the specification accepts degraded stereo at traffic speed.
- **Every street needing two same-direction passes names a different lane group for
  each.** There are 8,431 such instructions.
- **Every GPX file matches its solved route arc for arc.** We test this explicitly
  because a track that parses cleanly but diverges from the solution is the worst
  possible failure — it looks fine and sends the driver somewhere else.
- **The whole pipeline is deterministic.** Run it twice and you get byte-identical
  results. We verified this across three independent full runs.

### What is not proven

**The routes are not proven optimal.** Here is exactly where the inexactness lives,
and how big each piece is.

*The routing within a day, given a fixed orientation and a fixed zone, is exact.*
Min-cost flow with lower bounds solves it to proven optimality in polynomial time.
This is the largest single component of the work and it is not a heuristic.

*The connectivity repair is a heuristic.* A balanced flow can come back in several
disconnected pieces, each perfectly valid on its own and mutually unreachable — the
whole-city solve produced 331 of them. Joining them up is the genuinely NP-hard
part of the problem, and we do it greedily. We measured what it costs: 1.8 hours
out of 272, about two-thirds of one per cent. A better algorithm could recover some of that and not much
more.

*The zone partition is a heuristic.* We do not claim the 50-way split is the best
possible. We do know every zone is connected and that no day overruns. The days are
not evenly filled, though: they average 7.3 hours against a 9-hour window and range
from 4.2 to 8.6, with four days under six hours. Some of that is the two zones we
had to split late on, and some is that a zone's shape is dictated by the road
network rather than by how much work we would like to put in it. There is probably
a day or two recoverable here by a better partition, and we have not gone looking
for it.

*The orientation is a heuristic, and this is the one we would look at first.* For
each narrow two-way street somebody has to decide which direction counts as the
required one, and there are 30,533 such choices. We choose by minimising traffic
imbalance at junctions. We tested how much this matters by re-solving one typical
day under different orientations, and the answer is: **enormously**. An arbitrary
orientation costs 94% more — nearly double the day. Our heuristic is at least
*locally* good; every small perturbation we tried made the day worse. But we cannot
tell you how far it is from the best possible orientation, because finding out
would mean re-solving a day's flow for each of several hundred candidate flips, at
about eleven seconds each. That is the most promising piece of unfinished work in
the project, and it needs an incremental evaluator before it is affordable.

**On the headline gap.** The campaign drives 327.2 hours against a rigorously valid
floor of 159.8. That is a 105% gap and it looks alarming, so it deserves an
explanation: the floor counts the time to drive every required street plus the
cheapest possible way to leave each one, and *nothing else*. It allows no
repositioning at all, which is not a thing any real route can do. It is a valid
bound and a weak one. The better calibrated comparison is against the whole-city
tour: 327.2 hours for fifty days against 272.0 for one continuous circuit. The
55-hour difference is fifty round trips to a depot on the western edge of the city —
about 66 minutes a day of getting to work and home again.

### What is knowingly left out

**58.5 km of required street cannot be reached by any closed route** — 2% of the
requirement. Most of it (50.5 km) is in fragments the source data never connected
to the rest of the network; the remaining 8 km are legal traps, places you can
enter but not leave. We recovered 4.7 km of trapped motorway earlier by narrowing
one modelling rule that was inventing a restriction the road does not have. The
rest is either a data problem or a real one. It is reported, not absorbed, and it
needs a disposition before the driving starts.

**About 1,150 km of through-connected service roads are deferred.** These are
service-classified ways that function as streets — they link two real roads and
carry traffic. They were dropped for schedule certainty, deliberately and on the
record, and re-including them is a one-line configuration change. If that second
phase does not actually get scheduled, that kilometrage is simply lost, and it is
worth being clear-eyed about that now rather than in November.

---

## 8. Every assumption in one place

We have tried to collect here everything that is assumed rather than measured, so
that a reader can see the whole exposure at once.

**Speeds.** Free-flow speeds by road class (motorway 90 down to service 20 km/h)
are reasoned from Georgia's 60 km/h urban limit less the friction each class
implies. Posted limits override them where tagged, which is 9.5% of arcs.

**Congestion is entirely assumed.** There is no traffic data for Tbilisi in this
pipeline. We modelled it as a travel-time multiplier by road class and time of day
and we swept it: varying it from −25% to +50% moves the campaign estimate by about
6%. It is robust not because the assumption is good but because the 40 km/h capture
cap absorbs most of it. This is the weakest input in the model and it barely
matters — which is itself worth knowing.

**Turn penalties are assumed and unvalidated.** Straight-on 0 seconds, right 3,
left 8, U-turn 20. These are the specification's own approximations, still marked
as unconfirmed, and never measured against a real vehicle. Turn time is 57.1 hours —
17% of all driving — and it scales linearly with these four numbers. **A stopwatch
at twenty junctions would retire the largest remaining unvalidated assumption in
the model.** We would recommend doing that before the campaign rather than after.

**Surface.** 60% of required kilometres have no surface tag. We assume those are
paved, which follows the observed distribution among tagged streets. If they all
behaved like the tagged population instead, the campaign would be about 6% longer.

**Road width barely features.** Width is tagged on 1.6% of arcs, so the term that
slows the car on narrow streets fires on almost nothing. We implemented it because
it is specified and because it can be fitted from real traces later, not because it
changes this answer.

**The narrow-pair rule is the largest unmeasured assumption in the coverage model.**
Some 30,533 two-way streets in the scope we are driving are treated as capturable
in one pass from either direction — several thousand kilometres of road — and that
judgement is made on road class alone, because width is tagged on almost nothing.
If it turns out to be wrong for a share of them, one side of those streets is
missing and it surfaces at footage review, after the driving. This risk was raised,
considered, and knowingly accepted rather than measured, and it remains the single
place where the plan could be *incomplete* rather than merely inefficient.

**Repositioning overhead.** Zones are sized on a factor of 2.55 hours of driving per
hour of capture. This is measured, not guessed — it comes from solving all 48 zones
and taking the worst one — but it is measured from *our* routes, so it inherits
whatever slack they carry.

**Operating parameters** are as specified: 9-hour shift from 09:00, 45-minute break
inside it, seven days a week, no rest days modelled. Inserting rest days moves the
finish date and changes nothing else.

**Daylight** is modelled as sunset only. The specification also warns that the last
hour before sunset degrades — low sun, long shadows, glare — and we do *not* model
that. It is a capture-quality question, not a scheduling one, and nothing in this
pipeline measures it. If a later start pushes days into late October, that margin
should be taken off the window deliberately rather than discovered at review.

One assumption we withdrew, because it is instructive. An earlier stage credited the
plan with capturing streets during the drive out to each zone — a real and sensible
idea from the specification. When the routes were actually solved, they did not do
it: the legs pass through other zones at repositioning speed, capturing nothing. The
plan had banked about 12 hours of work its own solver did not deliver. We withdrew
the credit and the campaign got longer. **A plan may not bank a saving its solver
does not deliver**, and we would rather have the honest 50 days than a 38-day plan
built on a promise.

---

## 9. Four times the process caught something

We include these because they are the real argument for trusting the output, more
than any individual number is.

**A tour that was not a tour.** The circuit extraction, run on an unbalanced graph,
returns an *open* walk rather than failing. It has a plausible length, a plausible
map, and it is not a tour. A test written before the solver — deliberately, feeding
it routes broken in exactly one way each — caught it. We added an explicit balance
check.

**A GPX that drove one street too far.** Our first track repeated the first street
at the end of the day, on the reasoning that a circuit returns to its start. It does
— but it returns there by *finishing* the last street, so repeating the first one
leaves the driver a block from the depot. The closure test caught it. This is
exactly the class of error that would have survived a visual check of the map.

**A bound pointing the wrong way.** The specification's original wording would have
made an invariant test reject better plans. Caught by working through what the test
would actually assert.

**A plan that could not be driven.** Solving the first zoning produced 24 days out
of 38 that overran their shift. The zone sizing had inherited an overhead figure
from a problem without depot returns, and had also banked the commute capture
described above. Both were corrected and the plan re-solved; two remaining awkward
zones were split rather than shrinking every zone to accommodate them.

---

## 10. How to check any of this

Everything here is reproducible from the source data. `make all` runs the whole
pipeline end to end; each stage writes a JSON artifact holding every number its
report quotes, so no figure in any report can drift from the data behind it.

The gates run with `make gate` through `make gate5`. They deliberately re-derive
their answers from the published artifacts rather than from anything a solver kept
in memory — a test that asks a stage whether it did its job is not a test.

The per-stage reports carry the detail behind each summary here:

| Report | What it covers |
| --- | --- |
| `00-network-stats.md` | the extract, what was dropped and why |
| `01-turn-audit.md` | the manoeuvre graph, restrictions, traps |
| `02-time-model.md` | the speed model and every constant in it |
| `03-bounds.md` | the bracket, and where the gap comes from |
| `04-zoning.md` | the partition, routed depot legs, the calendar |
| `04b-recheck.md` | the scope re-test and the trapped motorways |
| `05-routes.md` | the fifty days, the turn account, orientation |

---

## In short

We have fifty legal, complete, drivable days that cover the agreed network and fit
their shifts, and we can prove each of those properties rather than assert them.
We cannot prove they are the shortest such fifty days, and the largest single
uncertainty is a choice we make 30,533 times — which direction counts as the
required one on each two-way street. We know that choice matters enormously and
that ours is locally sound. We do not know how much better the best one would be,
and we have said so rather than let the silence imply an answer.

If one thing gets done before the car goes out, it should be twenty minutes with a
stopwatch at a few junctions. The turn penalties are the last big number in this
model that nobody has ever checked.
