#!/usr/bin/env python3
"""Bundle a Stage 7 playback directory into ONE self-contained HTML file.

Why this exists: index.html loads its data with fetch("data/*.json"). Browsers
block fetch on file:// URLs (opaque origin), so double-clicking index.html always
fails with a resource error. index.html already checks window.PLAYBACK_EMBED
before falling back to fetch, so we simply inline every JSON under that key.

Usage:  python3 tools/make_standalone_playback.py <playback_dir> [out.html]
"""
import json, sys, pathlib

src = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
out = pathlib.Path(sys.argv[2]) if len(sys.argv) > 2 else src / "playback-standalone.html"
html = (src / "index.html").read_text(encoding="utf-8")

embed, total = {}, 0
for p in sorted((src / "data").glob("*.json")):
    key = f"data/{p.name}"
    embed[key] = json.loads(p.read_text(encoding="utf-8"))
    total += p.stat().st_size
    print(f"  + {key:24s} {p.stat().st_size/1e6:6.2f} MB")

blob = json.dumps(embed, separators=(",", ":"))
blob = blob.replace("</", "<\\/")          # never terminate the <script> early
blob = blob.replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")
tag = "<script>window.PLAYBACK_EMBED=" + blob + ";</script>\n"

i = html.find("<script")
if i == -1:
    raise SystemExit("no <script> tag found in index.html")
out.write_text(html[:i] + tag + html[i:], encoding="utf-8")

print(f"\n  {len(embed)} files, {total/1e6:.2f} MB inlined")
print(f"  -> {out}  ({out.stat().st_size/1e6:.2f} MB)")
print("  Open it directly. No server, no network, nothing external.")
