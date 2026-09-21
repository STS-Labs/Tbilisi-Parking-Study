"""A standing caveat stamped at the top of every report a campaign writes.

Some facts about a run are not findings, they are conditions, and a reader who
misses one misreads every number under it. Zone A is the live example: the customer
asked for zones A and B, `AB_zones.shp` contains only Zone B, and a Zone B result
read as an A+B result is wrong by however large Zone A turns out to be.

Putting that in the summary alone is not enough — the stage reports are read on
their own, linked to on their own, and quoted on their own. So it goes at the top
of each of them, from one configured string, and it regenerates with the report
rather than being pasted on afterwards by somebody who remembered.

Unset, `write` is `Path.write_text` and every existing campaign's reports come out
byte for byte as before.
"""

from __future__ import annotations

from pathlib import Path

from . import config as C


def banner() -> str:
    """The caveat block, already formatted as a Markdown quote, or empty."""
    text = (C.CAMPAIGN_CAVEAT or "").strip()
    if not text:
        return ""
    lines = "\n".join(f"> {line}".rstrip() for line in text.splitlines())
    return f"\n{lines}\n"


def stamp(text: str) -> str:
    """Insert the banner directly beneath the report's title.

    Beneath rather than above, because a document whose first line is not its
    heading renders wrong everywhere and reads as though the caveat were the title.
    A report with no heading gets it at the very top, which is the best available
    answer and never silently drops it.
    """
    block = banner()
    if not block:
        return text
    lines = text.split("\n")
    for index, line in enumerate(lines):
        if line.startswith("# "):
            return "\n".join(lines[: index + 1] + [block] + lines[index + 1:])
    return block + "\n" + text


def write(path: Path, text: str) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(stamp(text))
    return path


def stamp_existing(root: Path | None = None, skip=("day-",)) -> list[Path]:
    """Bring already-written reports up to date with the configured caveat.

    Reports regenerate with the caveat because `write` puts it there, but a stage
    that costs twenty minutes to re-run should not have to be re-run to add a line.
    This walks what is already on disk and inserts the same block in the same place,
    skipping anything that already carries it — so running it twice is a no-op and
    a later stage rerun produces the identical file.

    Driver turn sheets are skipped by default. The caveat is a provenance warning
    for whoever reads the numbers; on a turn sheet it is noise directly above the
    [UNVERIFIED] flags, which are what the driver actually has to act on.
    """
    block = banner()
    if not block:
        return []
    root = Path(root or C.REPORTS)
    touched: list[Path] = []
    for path in sorted(root.rglob("*.md")):
        if any(path.name.startswith(prefix) for prefix in skip):
            continue
        text = path.read_text()
        if block.strip() in text:
            continue
        path.write_text(stamp(text))
        touched.append(path)
    return touched
