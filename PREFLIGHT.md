# Pre-flight — check these on the rig BEFORE the car moves

Stage 6 turned up requirements that are **settings on the vehicle, not code**. If
the rig is wrong on day 1, the campaign silently produces damaged data and nobody
finds out until footage review, with the car long gone.

Ten minutes of checking. Do it before day 1.

---

## 1. GPS logging rate — **minimum 2 Hz, prefer 5–10 Hz**

`MIN_TRACE_RATE_HZ = 2`, measured, not assumed.

At 1 Hz and capture speed, consecutive fixes are **6.9 m apart**. Tbilisi's
network contains 4 m junction stubs — they fall *between* two fixes, get reported
as never driven, and are then re-planned every single day forever. The plan never
converges and the driver is sent back to a street they already filmed.

Higher is better. The matcher is gated at 1, 2, 5, 10 and 20 Hz.

## 2. Every fix must carry a timestamp

A GPX with no `<time>` elements now yields **almost no coverage, deliberately**.

Speed is a condition of valid capture (SPEC §10.3). Without timestamps there is no
speed, and an untestable condition is not a satisfied one. Earlier behaviour
invented one-second spacing, which made coverage an artefact of how densely the
exporter happened to place vertices.

Check the actual exported file, not the device's settings screen.

## 3. Log camera-recording state, and sync the clocks

**A GPS trace proves the car was there. It does not prove the camera was on.**

If the Stereolabs rig exposes recording state or footage timestamps, log them
alongside the trace so coverage can be cross-checked against actual footage. If it
cannot, that limitation must be stated in every coverage report rather than assumed
away — the coverage figure is then "the car drove here", not "this was filmed".

Sync the GPS clock and the camera clock before day 1 and note the offset.

## 4. Export format

GPX, CSV or NMEA all parse. Confirm which the rig produces and run one short
sample through `make stage6` **before** day 1, not after it.

---

## Day 1 is a calibration run — treat it as one

Three constants are pinned as **provisional** and cannot be calibrated from
synthetic data, because a synthetic trace is generated from the arc geometry and
therefore sits 0.00 m from the correct arc. It can prove a threshold is not too
tight; it says nothing about how loose it can safely be.

| Constant | Status | What day 1 gives it |
|---|---|---|
| `MATCH_MAX_CANDIDATE_DIST_M` | provisional | real GPS scatter, incl. hillside multipath |
| Turn coefficients (SPEC §3.3) | **[CONFIRM]** | junction dwell times — 17.4% of all driving |
| Speed model + downhill/uphill ratio | assumed | actual speeds by class and gradient |
| GPS error model (Stage 6 fixtures) | assumed | the real noise distribution |

**Suggested shape for day 1:** drive one zone. Run `make stage6` on the trace.
Read the report — match confidence distribution, marginal-band km, the
carriageway-separation figure — *before* committing to the remaining 46 days.

If the confidence distribution looks wrong, it is far cheaper to find out after one
day than after twenty.

---

## Standing rule

`prompts/06` sets it and it bears repeating here, because it is the whole point of
the stage: **when a match is marginal, the arc stays required.** Re-driving a
street costs an hour. Discovering a hole in the data after the campaign costs the
campaign.
