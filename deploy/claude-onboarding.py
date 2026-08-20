#!/usr/bin/env python3.13
"""Mark Claude Code onboarding complete for the workshop participant.

Merges into an existing ~/.claude.json so the bootstrap's preflight invoke keeps
whatever it wrote. lastOnboardingVersion must match the pinned CLI version or the
first-run flow, including the text-style picker, reappears.
"""

import json
import pathlib
import sys

version = sys.argv[1]
path = pathlib.Path.home() / ".claude.json"
try:
    config = json.loads(path.read_text(encoding="utf-8"))
except (OSError, ValueError):
    config = {}
config["hasCompletedOnboarding"] = True
config["lastOnboardingVersion"] = version
path.write_text(json.dumps(config, indent=2), encoding="utf-8")
path.chmod(0o600)
