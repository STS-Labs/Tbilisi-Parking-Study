"""Stage 6 item 3 — the exceptions register.

The operationally essential one. A street that turns out to be gated, walled off or
permanently under construction is not a planning failure to be re-solved; it is a
fact about the city. Without somewhere to record it, the re-planner sends the car
back to the same locked gate every morning for the rest of the campaign, and the
driver has no way to say so.

The register is a CSV on purpose. It is the one artifact a person edits — from a
phone, at the roadside, in a hurry — so it has to be legible and repairable without
tooling. Everything else in `data/derived/` is machine-written and regenerable;
this is neither, which is why it lives under version control alongside the surveys
rather than being rebuilt.

Retired kilometres are reported, never silently dropped. They cap what "complete
coverage" can mean, and a completion figure that quietly excludes them is a lie of
omission — CLAUDE.md rule 4.
"""

from __future__ import annotations

import csv
from dataclasses import asdict
from pathlib import Path

from . import config as C
from .coverage import Exception_

FIELDS = ("arc_id", "reason", "date", "reporter", "permanence")

#: Recognised reasons. Free text is accepted — a driver at a locked gate should not
#: be fighting a vocabulary — but these are the ones the report groups by.
KNOWN_REASONS = (
    "closed-permanently",
    "gated",
    "too-narrow",
    "under-construction",
    "private",
    "blocked",
    "other",
)


def write(entries: list[Exception_], path: Path | None = None) -> Path:
    path = path or C.EXCEPTIONS_CSV
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        for entry in sorted(entries, key=lambda e: (e.date, e.arc_id)):
            row = asdict(entry)
            row["permanence"] = "permanent" if row.pop("permanent") else "temporary"
            writer.writerow(row)
    return path


def read(path: Path | None = None) -> list[Exception_]:
    """Read the register. A missing file is an empty register, not an error."""
    path = path or C.EXCEPTIONS_CSV
    if not Path(path).exists():
        return []
    entries: list[Exception_] = []
    with open(path, newline="", encoding="utf-8") as handle:
        for line, row in enumerate(csv.DictReader(handle), start=2):
            arc_id = (row.get("arc_id") or "").strip()
            if not arc_id:
                continue
            permanence = (row.get("permanence") or "permanent").strip().lower()
            if permanence not in ("permanent", "temporary"):
                raise ValueError(
                    f"{path}:{line}: permanence must be 'permanent' or 'temporary', "
                    f"got {permanence!r}"
                )
            entries.append(
                Exception_(
                    arc_id=arc_id,
                    reason=(row.get("reason") or "other").strip(),
                    date=(row.get("date") or "").strip(),
                    reporter=(row.get("reporter") or "").strip(),
                    permanent=permanence == "permanent",
                )
            )
    return entries


def apply(state, entries: list[Exception_], today: str | None = None) -> dict:
    """Retire what the register says is undrivable, and restore what has aged out.

    Idempotent: applying the same register twice retires nothing new, so a day can
    be re-ingested without the accounting drifting.
    """
    already = {(e.arc_id, e.date) for e in state.exceptions}
    retired = []
    for entry in entries:
        if (entry.arc_id, entry.date) in already:
            continue
        key = state.retire(entry.arc_id, entry.reason, entry.date,
                           entry.reporter, entry.permanent)
        if key:
            retired.append(key)
    restored = state.restore_expired(today) if today else []
    return {
        "retired_keys": retired,
        "restored_keys": restored,
        "retired_km": state.retired_km(),
        "entries": len(state.exceptions),
    }
