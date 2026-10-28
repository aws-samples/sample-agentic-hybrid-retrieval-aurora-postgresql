#!/usr/bin/env python3
"""Close a Code Editor start-up race that can leave the Explorer empty and no terminal.

VS Code's WorkspaceService (src/vs/workbench/services/configuration/browser/
configurationService.ts) completes a multi-root workspace once its workspace file has
loaded. For a remote workspace that load can finish before `this.workspace` exists.
The update handler then throws "Cannot set properties of undefined (setting
'initialized')", and initialize() keeps the workspace's stale `initialized = false`,
so the workspace never completes: the Explorer keeps its loading clock and shows only
Outline and Timeline, and the folder-open terminal task never runs. On a test event
(Code Editor 1.101.2, 28 October 2026) 6 of 10 fresh-profile loads of
Mosaic.code-workspace stalled this way; after this patch 0 of 20 did.

The patch guards the handler and, in initialize(), re-reads the workspace file's state
before the completion check. It matches the bundle's shape, not the minifier's names,
leaves a build it does not recognise unchanged, and a second run changes nothing. It
is adapted from the Pellier workshop's patch for the same build.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

MARK = "/*mosaic-workspace-race*/"
ID = r"[\w$]+"
HANDLER = re.compile(
    rf"onDidUpdateConfiguration\((?P<e>{ID})=>\{{this\.{ID}\((?P=e)\)\.then\(\(\)=>\{{"
    rf"(?P<body>this\.(?P<ws>{ID})\.initialized=this\.(?P<cfg>{ID})\.initialized,"
    rf"this\.(?P<complete>{ID})\((?P=e)\))\}}\)"
)
INITIALIZE = re.compile(
    rf"await this\.{ID}\({ID},{ID}\),(?P<check>this\.(?P<complete>{ID})\(!1\),"
    rf"{ID}\(\"code/didInitWorkspaceService\"\))"
)


def patch(bundle: str) -> tuple[str, str]:
    """Patch the workbench bundle's two race sites.

    Args:
        bundle: The text of Code Editor's out/vs/code/browser/workbench/workbench.js.

    Returns:
        The bundle and what happened to it: "patched", "already patched", or
        "unrecognised (...)" with the bundle unchanged.
    """
    if MARK in bundle:
        return bundle, "already patched"
    handlers = list(HANDLER.finditer(bundle))
    inits = list(INITIALIZE.finditer(bundle))
    if len(handlers) != 1 or len(inits) != 1:
        found = f"{len(handlers)} handlers, {len(inits)} initialize sites"
        return bundle, f"unrecognised ({found})"
    handler, init = handlers[0], inits[0]
    if handler["complete"] != init["complete"]:
        return bundle, "unrecognised (the two sites name different completion checks)"
    ws, cfg = handler["ws"], handler["cfg"]
    guarded = f"this.{ws}&&({handler['body']})"
    resync = (
        f"this.{ws}.initialized=this.{ws}.initialized||this.{cfg}.initialized{MARK},"
    )
    edits = sorted(
        [(handler.span("body"), guarded), (init.span("check"), resync + init["check"])],
        reverse=True,
    )
    for (start, end), text in edits:
        bundle = bundle[:start] + text + bundle[end:]
    return bundle, "patched"


def main() -> None:
    """Patch each named workbench.js in place and print one outcome line per file."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "workbench",
        nargs="+",
        type=Path,
        help="Code Editor's out/vs/code/browser/workbench/workbench.js",
    )
    for path in parser.parse_args().workbench:
        bundle, outcome = patch(path.read_text(encoding="utf-8"))
        if outcome == "patched":
            path.write_text(bundle, encoding="utf-8")
        print(f"{path}: {outcome}")


if __name__ == "__main__":
    main()
