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
| `make db-bootstrap-cached` | `Makefile` |
| `us.cohere.embed-v4:0` | the default in `service/config.py` |
| `python3.13`, `$REPO/.venv` | `check-python` and `VENV` in `Makefile` |

Rename a route or move a port and the box stops booting, which a participant
discovers as a CloudFormation wait-condition timeout. `tests/test_bootstrap_contract.py`
compares the script against each source above so that lands as a failing test here
instead.

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
