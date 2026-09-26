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

### Secrets: one value per use, and what CloudFormation must supply

The script previously reused one `CODE_EDITOR_PASSWORD` for four things: the
sudo user's OS password, the Code Editor connection token, nginx's
`X-Mosaic-Origin-Verify` origin check, and the curl commands that proved it.
Reusing one secret across unrelated purposes means compromising or rotating
any one of them affects all four, and it is now three separate values:

| Bootstrap variable | Where it is used | Where it comes from |
| --- | --- | --- |
| `CODE_EDITOR_OS_PASSWORD` | `chpasswd` for the sudo user only. Vestigial for actual login -- NOPASSWD sudo means nothing ever authenticates with it, and the participant reaches this box exclusively through the Code Editor's own session, never an OS login prompt. | Generated locally in the script, the same way as `APP_DB_PASSWORD` (`secrets.token_urlsafe(32)`). **Not a CFN input**; nothing outside this script ever reads it. |
| `CODE_EDITOR_CONNECTION_TOKEN` | `code-editor-server --connection-token`, and the token file it reads on start. | **Must remain a CFN-supplied secret.** CloudFormation's `CodeEditorURL` stack output has to embed this same value as its `tkn=` query parameter, so CloudFormation has to know it; the bootstrap cannot generate it locally and report it back. |
| `ORIGIN_VERIFY_SECRET` | The nginx `X-Mosaic-Origin-Verify` check on both server blocks, and the API's own independent verification of the same header (`MOSAIC_ORIGIN_VERIFY_SECRET` in `.env`; see `docs/api-contract.md`). | **Must remain a CFN-supplied secret.** CloudFront's distribution config sets the custom origin header it forwards to nginx at stack-deploy time, before this script ever runs, so the value has to be known to CloudFormation up front -- the bootstrap cannot generate it locally and hand it to an already-configuring CloudFront distribution. |

The sibling CloudFormation template (out of view from this repository) needs
updating for the last two rows: rename or replace whatever currently
generates and passes `CODE_EDITOR_PASSWORD` with two separate generated
secrets, passed into the EC2 UserData as `CODE_EDITOR_CONNECTION_TOKEN` and
`ORIGIN_VERIFY_SECRET`, and configure the CloudFront distribution fronting
this host's port 8081 (and 80, for the editor) to forward
`ORIGIN_VERIFY_SECRET` as the `X-Mosaic-Origin-Verify` custom origin header.
Either generator is fine as long as it excludes `"`, `\`, and `$` -- the
bootstrap asserts `ORIGIN_VERIFY_SECRET` is letters, digits, `-`, and `_`
only before substituting it into nginx's config, because those three
characters would break out of nginx's double-quoted string literal or its
own variable interpolation.

The nginx `/api/` location also carries `limit_req`/`limit_conn` directives
(`mosaic_api_perip`, `mosaic_api_room`, `mosaic_api_conn`) sized for a full
workshop room; see `docs/api-contract.md` for the exact numbers and the
independent application-level admission control behind them.

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

## Local development

`make api-serve` runs `service.main:app` directly, with no nginx and no
CloudFront in front of it. `MOSAIC_REQUIRE_ORIGIN_VERIFICATION` defaults to
`true` (fail closed; see `docs/api-contract.md`), so a fresh clone's `.env`
copied from `config/.env.example` with no further changes cannot boot the API
at all: it refuses to start serving without a configured
`MOSAIC_ORIGIN_VERIFY_SECRET`. For loopback-only local development, set
`MOSAIC_REQUIRE_ORIGIN_VERIFICATION=false` in `.env` -- never in a deployment
reachable from anywhere but the API process's own machine, and never in
`deploy/mosaic-bootstrap.sh`, which always sets `true` with a generated
secret instead.

## Clean-account rehearsal and load exercise

[`docs/rehearsal-runbook.md`](../docs/rehearsal-runbook.md) is the runbook for
`READINESS.md`'s clean-account acceptance test: `scripts/rehearsal.py` records
deployment identity, archive transfer, bootstrap timings, catalog restore
verification, each lab's independent rehearsal, reranker/Ask Mosaic cold and
warm calls, and a layout walkthrough into one machine-readable evidence
manifest. `scripts/load_exercise.py` is a separate, opt-in bounded concurrency
exercise against the deployed HTTP API, meant to check the access-control
work's admission and timeout behavior once that lands. Neither tool deploys,
provisions, or resets anything itself; both need an authorized, already-running
Aurora and API environment that this repository's own offline tests cannot
provide.
