#!/usr/bin/env python3
"""
Inject the generated fixtures into the workbench template.

The template never contains data. The workbench is emitted from
fixtures/ui-model.json + fixtures/tool-parity-golden.json, both of which are
themselves emitted by fixtures/generate.py. So the chain from arm orderings to
the number on screen has no hand-copied link in it.

    fixtures/generate.py  ->  ui-model.json + tool-parity-golden.json
                          ->  ui/build.py
                          ->  ui/verity-workbench.html   (self-contained)

Run: python3 ui/build.py
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = ROOT / "ui" / "workbench.template.html"
OUT = ROOT / "ui" / "verity-workbench.html"


def main() -> None:
    # Regenerate first so the page can never be built from stale fixtures.
    subprocess.run([sys.executable, str(ROOT / "fixtures" / "generate.py")],
                   check=True, cwd=ROOT, stdout=subprocess.DEVNULL)

    model = json.loads((ROOT / "fixtures" / "ui-model.json").read_text())
    golden = json.loads((ROOT / "fixtures" / "tool-parity-golden.json").read_text())

    html = TEMPLATE.read_text(encoding="utf-8")
    for token, obj in (("/*__MODEL__*/", model), ("/*__GOLDEN__*/", golden)):
        if token not in html:
            raise SystemExit(f"template is missing {token}")
        html = html.replace(token, json.dumps(obj, separators=(",", ":")))

    # Self-containment: no remote fonts, no external scripts, no browser storage.
    for pattern, why in (
        (r"https?://fonts\.", "remote font"),
        (r"<script[^>]+src=", "external script"),
        (r"<link[^>]+stylesheet", "external stylesheet"),
        (r"\b(localStorage|sessionStorage)\b", "browser storage"),
    ):
        hit = re.search(pattern, html)
        if hit:
            raise SystemExit(f"self-containment violation ({why}): {hit.group(0)!r}")

    OUT.write_text(html, encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)}  ({len(html):,} bytes, self-contained)")


if __name__ == "__main__":
    main()
