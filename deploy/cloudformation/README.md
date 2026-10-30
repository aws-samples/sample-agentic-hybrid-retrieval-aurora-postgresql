# CloudFormation templates and editor launcher

This repository owns the templates, the editor launcher and its packager. Workshop
Studio keeps no copy of its own edits: its repin step copies these files and rewrites
only the pinned `Default:` lines (`SourceRevision`, `InfrastructureRevision`,
`BootstrapScriptSha256`, `EditorLauncherArchiveName`, `EditorLauncherCodeSha256`).
Change a template here, never in the Studio repository.

| File | Role |
| --- | --- |
| `hybrid-retrieval-main.yml` | Root stack. Nests the three templates below. |
| `hybrid-retrieval-vpc.yml`, `hybrid-retrieval-database.yml`, `hybrid-retrieval-code-editor.yml` | Nested stacks, loaded from `releases/<InfrastructureRevision>/`. |
| `hybrid-retrieval-staging.yml` | Own-account only: Aurora plus a builder host for building the catalog bundle before the main stack exists. |
| `editor_launcher.py`, `editor_launcher_package.py` | The Lambda that finds capacity for the Code Editor host, and the deterministic packager that names its archive `editor-launcher-<sha16>.zip`. |

`editor_launcher.py` is excluded from `ruff format`: its bytes are hashed into the archive
name the main template pins, so reformatting it would change the pin.

## RepoUrl

`RepoUrl` accepts any HTTPS GitHub URL ending in `.git`
(`^https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\.git$`), in the main and Code Editor
templates. Events keep the `aws-samples` URL through the Studio contentspec default; an
own-account deploy passes your fork. The host clones it anonymously, so the repository
must be public.

## Own-account deploys

`deploy/own-account/deploy.py` always passes the five pinned parameters explicitly,
computed from these files and the checkout, so the template `Default:` values never decide
a deploy. It derives `InfrastructureRevision` with the same digest as Studio's
`scripts/validate_workshop.py`. `tests/test_own_account_deploy.py` reverts the two `RepoUrl`
patterns in memory and asserts the digest equals Studio's pin (`11748fc9316005c9`), so a
drift in either copy of the algorithm or the templates fails the test.

The catalog bundle never touches a git remote. The flow:

1. `deploy.py staging up` creates your private bucket (tagged `MosaicOwnAccount=true`; an
   existing bucket without the tag is refused), publishes the nested templates to it and creates
   the staging stack, passing the bucket name in. The stack name must be free. The builder's
   user-data writes `MOSAIC_OWN_ACCOUNT_BUCKET` and `MOSAIC_OWN_ACCOUNT_PREFIX` to
   `/etc/mosaic-own-account.env`, which every login shell exports. Its role may get and put only
   under `real-catalog/*` and `contracts/*`, and list the bucket (S3 answers a missing key with
   403 instead of 404 without `s3:ListBucket`).
2. On the builder, `mosaic-catalog-bundle` starts the build detached (`setsid`, `nohup`, output in
   `/workshop/catalog-bundle.log`), so a dropped Session Manager session does not stop it.
   Running it again resumes from the saved state. The build uploads `real-catalog/...` and
   `contracts/real-catalog-cache.json` plus `contracts/corpus-vocabulary-cache.json`, each object
   carrying `sha256=<hex>` metadata.
3. `deploy.py staging down` checks that both contracts exist with `sha256` metadata (the build uploads
   them last, so they prove completion) and refuses without `--force` if not. It is
   safe as soon as the upload finished: the bucket belongs to the tool, not the stack. It then
   lists what the stack leaves behind (PostgreSQL log group, `RDSOSMetrics` streams, the KMS key's
   7-day window, the retained builder log group).
4. `deploy.py contracts pull` requires `sha256` metadata on both contracts, checks that the
   bucket holds the bundle they describe, and only then writes them into `db/config/` (temp file
   plus rename). Commit and push them.
5. `deploy.py publish` uploads templates, bootstrap, launcher and `RELEASE.json` from the clean
   checkout, then checks the bundle already in the bucket against the committed contracts
   (existence, size, `sha256` metadata) without downloading it. A local `--assets-dir` holding
   `real-catalog/` is an alternative: it is uploaded with the same metadata and verified the same
   way. Release keys are immutable; an existing key with other bytes or no metadata is refused.
6. `deploy.py deploy` creates the main stack from a clean tree whose `HEAD` equals
   `--source-revision`, after confirming the fork clones anonymously and the service-linked roles
   exist (`check` only reports them; `staging up` and `deploy` create them).

## Why publish waits on the global S3 endpoint

The main template is byte-identical to Workshop Studio's, and it loads its nested stacks from
`https://<bucket>.s3.amazonaws.com/...`. For a bucket created moments ago outside us-east-1 that
name answers with a 307 redirect until DNS catches up, and CloudFormation may not follow it.
`publish` therefore fetches `releases/<revision>/RELEASE.json` through that name with a signed
request that follows no redirect, printing "waiting for the bucket's global endpoint" until it
gets a 200. The staging template is ours and uses the Regional endpoint directly.

## WorkshopName comes from `--stack-name`

`deploy.py deploy` passes `WorkshopName` equal to the stack name (`--stack-name`, default
`mosaic-hybrid-retrieval`, so the default behaviour is unchanged). That is required for
correctness, not only for tidiness:

- `deploy/mosaic-bootstrap.sh` finds the host's Code Editor distribution with
  `aws cloudfront list-distributions --query "...[?Comment=='${WORKSHOP_NAME} Code Editor']..."`.
  `WORKSHOP_NAME` is the stack's `WorkshopName`. Two stacks sharing a name could resolve each
  other's distribution. Nothing else in the bootstrap matches resources by that name; it only
  labels things.
- The CloudFront-scope web ACL is named `${WorkshopName}-mosaic-api`. WAF names are unique per
  account and scope, so a second deployment with the default name fails in us-east-1, the only
  Region where the ACL exists.

The name must be 3 to 41 characters of lowercase letters, digits and hyphens, because the
templates restrict `WorkshopName`; `deploy` refuses anything else. As a guard against an earlier
deployment that already used the default name, `check` and `deploy` list the account's
CLOUDFRONT-scope web ACLs (always from us-east-1) and stop when `<WorkshopName>-mosaic-api`
exists, naming `--stack-name` as the fix. `check` also reports a stack with the same name as a
failure, the staging stack when it is up, and other stacks tagged `Workshop=<WorkshopName>` as
information.
