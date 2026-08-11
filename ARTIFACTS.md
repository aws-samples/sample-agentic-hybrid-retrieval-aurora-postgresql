# Artifacts and infrastructure

Where the live state lives, what can be restored, and what cannot.

## Infrastructure policy: Aurora only

**No local databases exist or will exist.**

- The **Aurora PostgreSQL cluster** in `us-east-1` holds the only live tree
  (`mosaic`, `mosaic_search`, `mosaic_eval`, `mosaic_bench`),
  500,000 products with real Cohere Embed v4 vectors at 1024 dimensions.
- The **cluster snapshot** is the only restore path. There is no local rebuild.
- Every `make` bootstrap target points at Aurora via `DATABASE_URL`.
- Any Makefile target, script, or document that assumes a local PostgreSQL is a
  defect.

Rationale is recorded in `docs/house-standards.md` §6. In short: the loaded state
of the pre-rewrite `catalog.*` tree existed only in two local databases, they
were dropped, and 500,000 rows of real embeddings cannot be reconstructed without
re-embedding. Local state that nothing can restore is not a convenience.

## What is restorable

| Artifact | Location | Restore path |
|---|---|---|
| Catalog + embeddings | Aurora `mosaic_*` | `mosaic-catalog-500k-cohere-v4-20260809` cluster snapshot |
| Embedding cache | `build/embedding-cache/` | `make db-import-embeddings` (keyed to `mosaic_*`) |
| Normalized CSV shards | `build/normalized/` | `make db-prepare-mosaic` from `data/full/*.csv.gz` |
| Premium cohort media | `ui/public/assets/images/mosaic/` | git; 126 files, content-verified |
| Lab contract | `data/evals/mosaic_labs_missions.json` | git; validated by `make validate-missions` |
| Retrieval numbers | `db/config/retrieval.yaml` | git; single source, enforced by `scripts/config_tripwire.py` |

## What is not restorable

**The `catalog.*` tree's loaded state.** Two local databases —
`catalog_workshop` and `catalog_codex_20260807` — held the only populated copy.
Both were dropped in August 2026. Verified 2026-08-10: neither exists, and the
live Aurora cluster has no `catalog` schema.

The historical DDL can be recovered from Git; the loaded data cannot.
Consequently, correctness is stated against live `mosaic_*`, not against a
reconstructed predecessor. See `docs/rewrite-losses.md`.

## Connecting from a corporate network

Environmental knowledge that otherwise lives in one engineer's shell history. This
cost an hour once; it should cost nobody a second one.

### Diagnose in this order

**Run `sslmode=disable` first.** It splits connectivity from TLS in one command:

```sh
psql "postgresql://USER:PASS@HOST:5432/mosaic_catalog?sslmode=disable" -c 'SELECT 1'
```

| Result | Meaning |
|---|---|
| `FATAL: no pg_hba.conf entry for host "X.X.X.X" ... no encryption` | **The network and the security group are fine.** The server saw you and rejected the unencrypted connection. The problem is TLS — go to the remedy below. |
| `timeout expired` | Traffic is not arriving. Security group or egress. |

Do not start with the security group. A reachable port plus a hanging session
looks like a firewall problem and is not one: `nc -z HOST 5432` reported OPEN, and
a raw SSLRequest packet got `S` back, while `psql` still timed out.

### Remedy on an Amazon office network: `sslnegotiation=direct`

The corporate middlebox breaks PostgreSQL's **negotiated** TLS — send
`SSLRequest`, then upgrade the socket in place — but passes TLS from the first
byte.

```
sslmode=require                        → hangs
sslmode=prefer                         → hangs
sslmode=require&sslnegotiation=direct  → works
```

`.env`'s `DATABASE_URL` carries `&sslnegotiation=direct`. **Single-quote the
value** or `set -a && . ./.env` dies with `parse error near '&'` — the ampersand is
a shell background operator. Needs a PostgreSQL 17+ libpq client; psycopg honors it
from the DSN.

### Security-group caveat: corporate NAT is a pool, not an address

`sg-05b26f41b295bc72d` gates the cluster and holds only `/32` rules. Amazon
corporate egress rotates across a pool — **two IPs were observed in a single
session** (`15.248.6.29`, `15.248.6.13`), and HTTP reflectors disagreed with each
other. DNS-based reflection is the reliable one:

```sh
dig +short myip.opendns.com @resolver1.opendns.com
aws ec2 authorize-security-group-ingress --region us-east-1 \
  --group-id sg-05b26f41b295bc72d \
  --ip-permissions 'IpProtocol=tcp,FromPort=5432,ToPort=5432,IpRanges=[{CidrIp=<ip>/32,Description="..."}]'
```

Two more things that mislead:

- **Rules propagate with a lag.** The first probe after authorizing still timed
  out; the port opened about a minute later. One failed try is not a failed rule.
- **The symptom returns.** If the pool rotates mid-session, working connections
  start timing out again. That is not a new problem — it is the same one with a new
  source address.

### Long sessions get dropped

Through the same middlebox, long-lived TLS sessions die with
`SSL error: unexpected eof while reading` while the cluster stays `available` and
an immediate reconnect succeeds. Measurement scripts that run for minutes should
retry and use one connection per sample, so a drop costs one datapoint rather than
the whole run.
