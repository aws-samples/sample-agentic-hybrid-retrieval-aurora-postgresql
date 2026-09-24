# Deploy inputs

## `mosaic-bootstrap.sh`

What Workshop Studio runs on the Code Editor instance to turn a bare Amazon Linux
box into a working Mosaic environment: packages, `uv sync`, the cached Aurora
bootstrap, the nginx front, and the `mosaic-api` and `mosaic-ui` units.

**This copy is the source of truth.** It lives here because almost everything in
it is a fact owned by this repository rather than by the workshop:

| The script hardcodes | This repository decides it in |
| --- | --- |
| `--port 8000` for the API | `API_PORT` in `Makefile` |
| `--port 5173` for Vite | `UI_PORT` in `Makefile` |
| `CATALOG_API_PROXY` | `ui/vite.config.ts` |
| `service.main:app` | `service/main.py` |
| `/api/health`, `/api/readiness` | the routes `service.main:app` registers |
| `make db-bootstrap-base` | `Makefile` |
| `us.cohere.embed-v4:0` | the default in `service/config.py` |
| `python3.13`, `$REPO/.venv` | `check-python` and `VENV` in `Makefile` |

Rename a route or move a port and the box stops booting, which a participant
discovers as a CloudFormation wait-condition timeout. `tests/test_bootstrap_contract.py`
compares the script against each source above so that lands as a failing test here
instead.

### Catalog selection and assets

The script first downloads and verifies the real-catalog archive against
`db/config/real-catalog-cache.json`. After the original cached bootstrap creates
the shared schemas, `scripts/real_catalog_cache.py restore` loads the selected
records, reuses saved vectors, creates the real search projection and imports the
reviewed excerpts. `MOSAIC_CATALOG_DATASET` is persisted before the API starts.
Runtime grants and lab SQL application cover `mosaic_live_search`; a repair must
not silently update only the historical `mosaic_search` schema.

Keep both the original 51-object embedding cache and the `real-catalog/real-catalog.tar.gz.part-*` files
in the Studio asset working copy. The latter is git-ignored and hash-pinned; no
embedding generation runs during provisioning. Public dataset redistribution
clearance and a fresh deployment still need event-owner verification.

### Coding coach in Code Editor

Participants open `CodeEditorURL` and run `claude` in its terminal. The
bootstrap installs Claude Code 2.1.233, enables Amazon Bedrock, and pins
`ANTHROPIC_MODEL=global.anthropic.claude-sonnet-5`. It uses the instance role;
participants do not need a personal Anthropic login. The lab's third hint
provides a scoped coaching prompt. `~/.claude/CLAUDE.md` requires diagnosis,
an edit limited to the current marked seam, and production validation.

The bootstrap proves an actual coach invocation before continuing. Workshop
Studio checks the shell, preflight, IAM resources and `ClaudeCodeModel` output
agree. The coach model is separate from the application's agent and synthesis
model settings. Event-account access still needs a fresh-stack rehearsal;
development-account access alone is insufficient.

### Delivery, and why the workshop repo keeps a copy

CloudFormation `UserData` runs before any clone exists, so it reads the script from
the per-event S3 bucket Workshop Studio populates from its `assets/` directory, then
verifies it against a `BootstrapScriptSha256` parameter before executing. Only then
does the script fetch this repository at a pinned `SOURCE_REVISION`. Publishing the
script over the internet instead would put github.com on the critical path of every
participant's stack creation during a live session.

So the workshop repository keeps a byte-identical copy, and this is the side that
gets edited:

```sh
make sync-bootstrap                     # copy this file into the workshop repo
make check-bootstrap-sync               # fail if the two have diverged
WORKSHOP_REPO=/path/to/repo make sync-bootstrap   # non-default checkout location
```

`make check-bootstrap-sync` skips when the workshop repository is not checked out
beside this one, so a plain clone of this repository still passes. Print the hash
CloudFormation needs with:

```sh
shasum -a 256 deploy/mosaic-bootstrap.sh
```

The first Code Editor terminal opens `START_HERE.md` through the editor's own
remote CLI with the built-in Markdown preview association, then leaves a login shell ready for the participant. The marker in
`.local/code-editor-started` prevents later visits from reopening the page over
a participant's work. The folder-open task runs in background mode so an idle
shell does not display a busy task spinner.
