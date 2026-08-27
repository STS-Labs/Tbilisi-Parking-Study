"""Parse OSM `type=restriction` relations into manoeuvre constraints (SPEC §3.3).

Three things here are easy to get wrong and are handled explicitly:

* **Via-way restrictions.** The via member is a way, not a node, so the
  constraint spans two manoeuvres rather than one.  They are parsed here and
  honoured in `turngraph` by cloning the via arc; they are *not* collapsed to a
  single edge removal, which would either miss the restriction or over-restrict.
* **Vehicle scope.** `restriction:hgv=no_left_turn` does not bind a car, and
  `except=motorcar` exempts one from a restriction that otherwise would.
* **`only_*` relations.** These forbid every manoeuvre from the `from` arc at the
  via node *except* the named `to` — the expensive half of the semantics, and the
  half a naive reading drops.

Nothing is discarded silently: every relation that is not applied leaves a row in
`skipped` carrying its relation id and a machine-readable reason.
"""

from __future__ import annotations

import collections
import re
from dataclasses import dataclass, field
from pathlib import Path

import osmium

#: Tag keys that scope a restriction to a vehicle class, most specific last.
CAR_RESTRICTION_KEYS: tuple[str, ...] = (
    "restriction",
    "restriction:motor_vehicle",
    "restriction:motorcar",
)
#: Vehicle classes whose appearance in `except` exempts the camera car.
CAR_EXCEPT_VALUES: frozenset[str] = frozenset({"motorcar", "motor_vehicle", "vehicle"})

MANOEUVRES: frozenset[str] = frozenset(
    {"left_turn", "right_turn", "u_turn", "straight_on", "entry", "exit"}
)

#: SPEC §5 shift window.
SHIFT_START_H = 9.0
SHIFT_END_H = 18.0


@dataclass(frozen=True)
class Restriction:
    """One applicable manoeuvre constraint."""

    relation_id: int
    kind: str  # "no" | "only"
    manoeuvre: str
    from_way: int
    to_ways: tuple[int, ...]
    via_nodes: tuple[int, ...] = ()
    via_ways: tuple[int, ...] = ()
    conditional: str = ""
    source_tag: str = "restriction"

    @property
    def is_via_way(self) -> bool:
        return bool(self.via_ways)


@dataclass
class ParsedRestrictions:
    applicable: list[Restriction] = field(default_factory=list)
    skipped: list[dict] = field(default_factory=list)
    found: int = 0

    @property
    def via_way_count(self) -> int:
        return sum(1 for r in self.applicable if r.is_via_way)

    @property
    def via_node_count(self) -> int:
        return sum(1 for r in self.applicable if not r.is_via_way)

    @property
    def by_type(self) -> dict[str, int]:
        counter: collections.Counter[str] = collections.Counter()
        for r in self.applicable:
            counter[f"{r.kind}_{r.manoeuvre}"] += 1
        return dict(sorted(counter.items()))

    @property
    def skipped_by_reason(self) -> dict[str, int]:
        counter: collections.Counter[str] = collections.Counter()
        for row in self.skipped:
            counter[row["reason"]] += 1
        return dict(sorted(counter.items()))


_TIME_RANGE = re.compile(r"(\d{1,2}):(\d{2})\s*-\s*(\d{1,2}):(\d{2})")
_ALL_DAYS = ("mo-su", "su-sa", "24/7", "mo-sun")


def condition_covers_shift(condition: str) -> bool:
    """Whether an OSM opening-hours condition covers the whole 09:00–18:00 shift.

    Deliberately conservative: only conditions that plainly span every day and the
    entire shift return True.  Anything it does not fully understand is treated as
    *not* covering, which leaves the restriction unapplied and logged rather than
    guessed at.  SPEC §5 runs 7 days a week, so a weekday-only condition never
    qualifies.
    """
    text = (condition or "").strip().lower()
    if not text:
        return False
    if "24/7" in text:
        return True
    if not any(day in text for day in _ALL_DAYS):
        return False

    match = _TIME_RANGE.search(text)
    if not match:
        # all days, no time range given -> applies at all times
        return True
    start = int(match.group(1)) + int(match.group(2)) / 60.0
    end = int(match.group(3)) + int(match.group(4)) / 60.0
    if end == 0.0:
        end = 24.0
    return start <= SHIFT_START_H and end >= SHIFT_END_H


def _restriction_value(tags: dict[str, str]) -> tuple[str, str, str]:
    """Return (value, source_tag, condition) for the tag that binds a car."""
    value = ""
    source = ""
    for key in CAR_RESTRICTION_KEYS:
        if tags.get(key):
            value, source = tags[key], key

    condition = ""
    for key in list(CAR_RESTRICTION_KEYS):
        conditional_key = f"{key}:conditional"
        if tags.get(conditional_key):
            condition = tags[conditional_key]
            if not value:
                source = conditional_key
    return value, source, condition


def _split_condition(raw: str) -> tuple[str, str]:
    """`"no_left_turn @ (Mo-Fr 07:00-09:00)"` -> ("no_left_turn", "Mo-Fr 07:00-09:00")."""
    if "@" not in raw:
        return raw.strip(), ""
    value, _, condition = raw.partition("@")
    return value.strip(), condition.strip().strip("()").strip()


def parse_restrictions(
    pbf_path: Path | str, network_way_ids: set[int]
) -> ParsedRestrictions:
    """Read every `type=restriction` relation that touches the network."""
    out = ParsedRestrictions()

    for relation in osmium.FileProcessor(str(pbf_path), osmium.osm.RELATION):
        tags = {k: v for k, v in relation.tags}
        if tags.get("type") != "restriction":
            continue

        members = [(m.type, m.ref, m.role) for m in relation.members]
        member_ways = {ref for kind, ref, _ in members if kind == "w"}
        if not member_ways & network_way_ids:
            continue  # not our network at all; Stage 0 already counted these

        out.found += 1
        skip = _skip_reason(relation.id, tags, members, network_way_ids)
        if skip is not None:
            out.skipped.append(skip)
            continue

        raw_value, source_tag, condition_tag = _restriction_value(tags)
        conditional = ""
        if not raw_value and condition_tag:
            raw_value, conditional = _split_condition(condition_tag)
        elif condition_tag:
            _, conditional = _split_condition(condition_tag)

        kind, _, manoeuvre = raw_value.partition("_")
        out.applicable.append(
            Restriction(
                relation_id=relation.id,
                kind=kind,
                manoeuvre=manoeuvre,
                from_way=next(ref for k, ref, role in members if k == "w" and role == "from"),
                to_ways=tuple(ref for k, ref, role in members if k == "w" and role == "to"),
                via_nodes=tuple(ref for k, ref, role in members if k == "n" and role == "via"),
                via_ways=tuple(ref for k, ref, role in members if k == "w" and role == "via"),
                conditional=conditional,
                source_tag=source_tag,
            )
        )

    return out


def _skip_reason(
    relation_id: int, tags: dict[str, str], members: list, network_way_ids: set[int]
) -> dict | None:
    """The single reason this relation is not applied, or None to apply it."""

    def row(reason: str, detail: str = "") -> dict:
        return {"relation_id": relation_id, "reason": reason, "detail": detail}

    raw_value, source_tag, condition_tag = _restriction_value(tags)
    if not raw_value and not condition_tag:
        vehicle_scoped = [k for k in tags if k.startswith("restriction")]
        if vehicle_scoped:
            return row("not_applicable_to_car", ",".join(sorted(vehicle_scoped)))
        return row("no_restriction_tag")

    excepted = {v.strip().lower() for v in tags.get("except", "").split(";") if v.strip()}
    if excepted & CAR_EXCEPT_VALUES:
        return row("not_applicable_to_car", f"except={tags.get('except')}")

    conditional = ""
    if not raw_value:
        raw_value, conditional = _split_condition(condition_tag)
        if not condition_covers_shift(conditional):
            return row("conditional_outside_shift", conditional)

    kind, _, manoeuvre = raw_value.partition("_")
    if kind not in ("no", "only") or manoeuvre not in MANOEUVRES:
        return row("unknown_restriction_value", raw_value)

    froms = [ref for k, ref, role in members if k == "w" and role == "from"]
    tos = [ref for k, ref, role in members if k == "w" and role == "to"]
    if len(froms) != 1 or not tos:
        return row("missing_from_or_to", f"from={len(froms)} to={len(tos)}")

    via_ways = [ref for k, ref, role in members if k == "w" and role == "via"]
    via_nodes = [ref for k, ref, role in members if k == "n" and role == "via"]
    if not via_ways and not via_nodes:
        return row("no_via_member")

    missing = [w for w in froms + tos + via_ways if w not in network_way_ids]
    if missing:
        return row("member_way_not_in_network", ",".join(str(w) for w in sorted(missing)))

    return None
