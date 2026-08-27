"""Stage 6 item 2 — what actually counts as covered, and what is still owed.

A traversal counts only when all of SPEC §10.3's conditions hold, and this module
is written so that every way of *not* counting has a name. A silent non-match and a
rejected match look the same in a coverage total and mean completely different
things operationally: one is a street nobody drove, the other is a street somebody
drove wrongly and will drive wrongly again tomorrow unless told.

**Requirements are keyed, not per-arc.** SPEC §2.2's narrow pairs are one
requirement satisfiable from either direction, so both arcs of a pair share a key
and covering either one discharges it. Everything else is keyed by its own
`arc_id`. This is what makes the accounting exact: `covered + remaining + retired`
equals the original requirement for every key, always.

**A GPS trace is evidence the car was there, not that the camera was on.** Until
the rig's footage timestamps are known to be readable, `recording_evidence` is
`unknown` and every report has to say so. It is not treated as proof either way —
the passes are counted, and the caveat travels with the number.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from . import config as C
from . import matcher as _matcher

#: Every reason a traversal can fail to count. Reported verbatim, because "not
#: covered" without a reason is not actionable for the driver or the re-planner.
REASONS = (
    "counted",
    "partial",        # the run spanned too little of the arc to be a traversal
    "speed",          # driven faster than capture allows, and not a `reduced` arc
    "heading",        # driven the wrong way — SPEC §10.3
    "not-recording",  # positively known the rig was off
    "no-time",        # the trace carried no timestamps, so speed cannot be tested
    "retired",        # an exception has taken this arc out of the required set
    "satisfied",      # the requirement was already fully covered
)


def requirement_key(arc_id: str, pair_id, pair_requirement) -> str:
    """The key a traversal of this arc discharges.

    A narrow pair is one requirement for the street, not one per direction.
    """
    if pair_requirement and isinstance(pair_id, str) and pair_id:
        return pair_id
    return str(arc_id)


def _keys(arcs) -> dict:
    """Requirement key and passes owed, per key, from the arc table."""
    required: dict[str, int] = {}
    members: dict[str, list[str]] = {}
    quality: dict[str, str] = {}
    length: dict[str, float] = {}
    for row in arcs.itertuples(index=False):
        if bool(getattr(row, "excluded", False)):
            continue
        if not bool(getattr(row, "in_largest_scc", True)):
            continue
        passes = int(getattr(row, "min_passes", 0) or 0)
        if passes <= 0:
            continue
        key = requirement_key(row.arc_id, getattr(row, "pair_id", ""),
                              getattr(row, "pair_requirement", 0))
        # A pair's two arcs carry the same requirement; take it once, not twice.
        required[key] = max(required.get(key, 0), passes)
        members.setdefault(key, []).append(str(row.arc_id))
        quality[str(row.arc_id)] = str(getattr(row, "capture_quality", "full"))
        length[key] = max(length.get(key, 0.0), float(getattr(row, "length_m", 0.0)))
    return {"required": required, "members": members, "quality": quality,
            "length_m": length}


@dataclass(frozen=True)
class Verdict:
    """One decoded run, and whether it discharged anything."""

    arc_id: str
    key: str
    counted: bool
    reason: str
    fraction: float
    speed_kmh: float
    heading_delta_deg: float
    first_fix: int
    last_fix: int


@dataclass
class Exception_:
    arc_id: str
    reason: str
    date: str
    reporter: str
    permanent: bool = True


@dataclass
class CoverageState:
    """What is covered, what is still owed, and what has been retired."""

    required: dict[str, int]
    remaining: dict[str, int]
    covered: dict[str, int] = field(default_factory=dict)
    retired_passes: dict[str, int] = field(default_factory=dict)
    exceptions: list[Exception_] = field(default_factory=list)
    members: dict[str, list[str]] = field(default_factory=dict)
    quality: dict[str, str] = field(default_factory=dict)
    length_m: dict[str, float] = field(default_factory=dict)

    @classmethod
    def initial(cls, arcs) -> "CoverageState":
        parts = _keys(arcs)
        required = parts["required"]
        return cls(
            required=dict(required),
            remaining=dict(required),
            covered={k: 0 for k in required},
            retired_passes={k: 0 for k in required},
            members=parts["members"],
            quality=parts["quality"],
            length_m=parts["length_m"],
        )

    # -- the required set -----------------------------------------------------
    def key_of(self, arc_id: str) -> str | None:
        for key, arc_ids in self.members.items():
            if arc_id in arc_ids:
                return key
        return None

    def outstanding(self) -> dict[str, int]:
        """Keys still owing passes. This is what Stages 4-5 re-plan over."""
        return {k: v for k, v in self.remaining.items() if v > 0}

    def retired_km(self) -> float:
        return sum(self.length_m.get(k, 0.0) for k, v in self.retired_passes.items()
                   if v > 0) / 1000.0

    def coverage_fraction(self) -> float:
        total = sum(self.required.values())
        return sum(self.covered.values()) / total if total else 1.0

    # -- mutation -------------------------------------------------------------
    def credit(self, key: str, passes: int = 1) -> int:
        """Discharge up to `passes` of a requirement. Never goes below zero."""
        owed = self.remaining.get(key, 0)
        taken = min(owed, passes)
        if taken:
            self.remaining[key] = owed - taken
            self.covered[key] = self.covered.get(key, 0) + taken
        return taken

    def retire(self, arc_id: str, reason: str, date: str, reporter: str,
               permanent: bool = True) -> str | None:
        """Take an undrivable street out of the required set.

        Item 3 of the brief: without this the re-planner sends the car back to a
        gated street every single day. Whatever is still owed becomes retired, so
        the accounting stays exact rather than the requirement simply vanishing.
        """
        key = self.key_of(arc_id)
        if key is None:
            return None
        owed = self.remaining.get(key, 0)
        if owed:
            self.remaining[key] = 0
            self.retired_passes[key] = self.retired_passes.get(key, 0) + owed
        self.exceptions.append(
            Exception_(arc_id=arc_id, reason=reason, date=date,
                       reporter=reporter, permanent=permanent)
        )
        return key

    def restore_expired(self, today: str) -> list[str]:
        """Return temporary exclusions to the required set once they have aged out."""
        from datetime import date as _date

        def parse(text):
            return _date.fromisoformat(text)

        restored = []
        for entry in list(self.exceptions):
            if entry.permanent:
                continue
            if (parse(today) - parse(entry.date)).days < C.TEMPORARY_EXCEPTION_DAYS:
                continue
            key = self.key_of(entry.arc_id)
            if key is None:
                continue
            back = self.retired_passes.get(key, 0)
            if back:
                self.retired_passes[key] = 0
                self.remaining[key] = self.remaining.get(key, 0) + back
                restored.append(key)
            self.exceptions.remove(entry)
        return restored

    # -- persistence ----------------------------------------------------------
    def to_dict(self) -> dict:
        return {
            "required": self.required,
            "remaining": self.remaining,
            "covered": self.covered,
            "retired_passes": self.retired_passes,
            "exceptions": [vars(e) for e in self.exceptions],
            "members": self.members,
            "quality": self.quality,
            "length_m": self.length_m,
        }

    @classmethod
    def from_dict(cls, payload: dict) -> "CoverageState":
        return cls(
            required=payload["required"],
            remaining=payload["remaining"],
            covered=payload.get("covered", {}),
            retired_passes=payload.get("retired_passes", {}),
            exceptions=[Exception_(**e) for e in payload.get("exceptions", [])],
            members=payload.get("members", {}),
            quality=payload.get("quality", {}),
            length_m=payload.get("length_m", {}),
        )

    def save(self, path: Path = None) -> Path:
        path = path or C.COVERAGE_STATE_JSON
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2, sort_keys=True))
        return path

    @classmethod
    def load(cls, path: Path = None) -> "CoverageState":
        path = path or C.COVERAGE_STATE_JSON
        return cls.from_dict(json.loads(path.read_text()))


@dataclass
class Outcome:
    verdicts: list[Verdict]
    state: CoverageState
    match: _matcher.MatchResult
    recording_evidence: str
    date: str | None = None

    @property
    def gained(self) -> int:
        return sum(1 for v in self.verdicts if v.counted)


def ingest(trace, arcs, state: CoverageState | None = None, date: str | None = None,
           recording=None, **match_kwargs) -> Outcome:
    """Take a day's trace and work out what it actually covered.

    `recording` may be a callable `(t0, t1) -> bool` answering whether the rig was
    recording over an interval, once the footage timestamps are readable. Absent
    that, `config.RECORDING_EVIDENCE_AVAILABLE` is False, the evidence is reported
    as `unknown`, and no traversal is rejected on those grounds — rejecting on an
    unknown would silently discard real coverage, and accepting silently would
    overstate it. The number is counted and the caveat is carried with it.
    """
    state = state or CoverageState.initial(arcs)
    result = _matcher.match(trace, arcs, **match_kwargs)

    evidence = "unknown"
    if C.RECORDING_EVIDENCE_AVAILABLE and recording is not None:
        evidence = "checked"

    verdicts: list[Verdict] = []

    for run in result.passes:
        key = state.key_of(run.arc_id)
        if key is None:
            continue  # not a required arc: deadhead, or out of scope
        quality = state.quality.get(run.arc_id, "full")
        reason = "counted"

        if not run.through and run.fraction < C.MATCH_MIN_ARC_FRACTION:
            reason = "partial"
        elif quality != "reduced" and not getattr(trace, "has_time", True):
            # No timestamps means no speed, and SPEC §10.3 makes speed a condition of
            # counting. An untestable condition is not a satisfied one.
            reason = "no-time"
        elif quality != "reduced" and run.speed_quantile_kmh > C.COVERAGE_SPEED_MAX_KMH:
            reason = "speed"
        elif evidence == "checked" and not recording(trace.t[run.first_fix],
                                                     trace.t[run.last_fix]):
            reason = "not-recording"
        elif state.retired_passes.get(key, 0) and not state.remaining.get(key, 0):
            reason = "retired"
        elif state.remaining.get(key, 0) <= 0:
            reason = "satisfied"

        counted = reason == "counted" and state.credit(key, 1) == 1
        if reason == "counted" and not counted:
            reason = "satisfied"
        verdicts.append(
            Verdict(arc_id=run.arc_id, key=key, counted=counted, reason=reason,
                    fraction=run.fraction, speed_kmh=run.speed_quantile_kmh,
                    heading_delta_deg=run.max_heading_delta_deg,
                    first_fix=run.first_fix, last_fix=run.last_fix)
        )

    for run in result.wrong_way:
        key = state.key_of(run.arc_id)
        if key is None or run.fraction < C.MATCH_MIN_ARC_FRACTION:
            continue
        verdicts.append(
            Verdict(arc_id=run.arc_id, key=key, counted=False, reason="heading",
                    fraction=run.fraction, speed_kmh=run.speed_quantile_kmh,
                    heading_delta_deg=run.max_heading_delta_deg,
                    first_fix=run.first_fix, last_fix=run.last_fix)
        )

    verdicts.sort(key=lambda v: (v.first_fix, v.arc_id))
    return Outcome(verdicts=verdicts, state=state, match=result,
                   recording_evidence=evidence, date=date)
