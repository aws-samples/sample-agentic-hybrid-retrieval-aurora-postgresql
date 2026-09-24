#!/usr/bin/env bash
# Open the participant entrypoint once, without stealing focus on later visits.
set -u
workshop_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
welcome_marker="$workshop_root/.local/code-editor-started"
if [ ! -e "$workshop_root/learning-notes.md" ]; then
  printf '# Learning notes\n\nRecord your prediction, observation, receipt IDs and explanation for each experiment.\n' >"$workshop_root/learning-notes.md"
fi
if [ ! -e "$welcome_marker" ] && command -v code >/dev/null 2>&1; then
  if code --reuse-window "$workshop_root/START_HERE.md" >/dev/null 2>&1; then
    mkdir -p "$workshop_root/.local"
    touch "$welcome_marker"
  fi
fi
exec bash -l
