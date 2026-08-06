#!/usr/bin/env bash
# Install repository hooks without replacing an existing global hook suite.
set -euo pipefail

ROOT_DIR="$(git rev-parse --show-toplevel)"
cd "$ROOT_DIR"

managed_hooks="$(git rev-parse --git-path workbench-hooks)"
if [[ "$managed_hooks" != /* ]]; then
  managed_hooks="$ROOT_DIR/$managed_hooks"
fi

existing_local="$(git config --local --get core.hooksPath || true)"
chained_hooks="$(git config --local --get workbench.chainedHooksPath || true)"

if [[ "$existing_local" == "$managed_hooks" && -n "$chained_hooks" ]]; then
  upstream_hooks="$chained_hooks"
else
  upstream_hooks="$(git config --path --get core.hooksPath || true)"
fi

if [[ -n "$upstream_hooks" && "$upstream_hooks" != /* ]]; then
  upstream_hooks="$ROOT_DIR/$upstream_hooks"
fi
if [[ "$upstream_hooks" == "$managed_hooks" ]]; then
  upstream_hooks="$chained_hooks"
fi

if [[ -n "$upstream_hooks" && ! -d "$upstream_hooks" ]]; then
  echo "ERROR: existing hooks path is not a directory: $upstream_hooks" >&2
  exit 1
fi

mkdir -p "$managed_hooks"
if find "$managed_hooks" -mindepth 1 -maxdepth 1 ! -type l -print -quit \
  | grep -q .
then
  echo "ERROR: managed hooks directory contains a non-symlink: $managed_hooks" >&2
  exit 1
fi
find "$managed_hooks" -mindepth 1 -maxdepth 1 -type l -delete

if [[ -n "$upstream_hooks" ]]; then
  for hook in "$upstream_hooks"/*; do
    if [[ -f "$hook" && -x "$hook" && "$(basename "$hook")" != "pre-push" ]]; then
      ln -s "$hook" "$managed_hooks/$(basename "$hook")"
    fi
  done
  git config --local workbench.chainedHooksPath "$upstream_hooks"
else
  git config --local --unset-all workbench.chainedHooksPath 2>/dev/null || true
fi

ln -s "$ROOT_DIR/scripts/git-hooks/pre-push" "$managed_hooks/pre-push"
git config --local core.hooksPath "$managed_hooks"

echo "Installed repository hooks at: $managed_hooks"
if [[ -n "$upstream_hooks" ]]; then
  echo "Chained existing hooks from:  $upstream_hooks"
else
  echo "No existing hooks path was configured."
fi
echo "The pre-push hook runs the chained hook before DAT410 security checks."
