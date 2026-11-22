# Event readiness

Each event box records whether it is ready for the event. A facilitator reads those
records from a laptop, for one account or for every account at once. DAT416 and DAT432
use the same command and the same table.

## The record

Bootstrap writes the record twice at most:

- After its acceptance gate passes and CloudFormation has heard SUCCESS. The record runs
  under its own 120-second cap, so it cannot hold the stack.
- When a bootstrap phase fails, before CloudFormation hears FAILURE. That record names the
  failing phase. A failure before the repository's environment exists leaves no record.
  A rollback deletes the stack's log group, and that record with it. In both cases the
  laptop reads CloudFormation instead. A stack in `CREATE_FAILED` or a `ROLLBACK_` state
  shows `❌ setup failed:` and the first failed resource's reason, read from the nested
  stacks' events even after the rollback deleted them. For a bootstrap failure that
  reason ends with the bootstrap log's last lines.

A record holds the UTC time, one line per check and a final line: `READY FOR LAB 1`, or
the first failing check. Root keeps it in `/var/lib/mosaic-readiness/record.json`, and it
goes to CloudWatch Logs, log group `/aws/mosaic/readiness`, one stream per instance. The
template creates the group and lets the instance role write only to it. Participants
never see the record.

The checks run as the participant, from the repository, through
`/usr/local/sbin/mosaic-readiness-record`. Every check reads. None resets a lab, runs a
search that writes an audit row, or runs the agent. They cover:

- **Versions that ran:** the source revision, Node, Python, uv, `psql`, Claude Code and
  Code Editor against what bootstrap installed
  (`/opt/mosaic-workshop/readiness-expected.json`), the Aurora engine and the pgvector
  and pg_trgm versions, both AgentCore runtimes on platform `V1`, and the booted AMI.
- **Evidence paths:** the services, the catalog counts and embedding model, the API's
  origin rule, the model IDs the API, both runtimes and the terminal use, Gateway's three
  SQL tools, Memory, the three Bedrock models, Docker and the bootstrap image for Lab 3's
  deploy, and Claude Code's managed settings.
- **State before participants start:** Lab 1 `BROKEN`, Labs 2 and 3 `NOT STARTED`.

The checks that need a write ran once in the bootstrap gate: Lab 1's broken search, a
reranked search, a Gateway search with evidence, the Session Memory round trip, Claude
Code's answer, the mission and evaluation checks, and Lab 2's validation. The record lists
each with the time the gate passed.

An absence counts as ready only after a positive control. Fuzzy matching must find the
Logitech (1492978) for both Lab 1's typo and the exact ID before the gate's "Logitech
absent" proves the fault. A runtime that reports no platform version fails, because a
missing value is not `V1`. A record in which no check passed is not ready.

### AgentCore Runtime platform

Both runtimes stay on platform `V1` until AWS retires it. Each gets one platform line,
worded the same in DAT410, DAT416 and DAT432 after the status, and every line but the
first makes the account not ready:

```text
PASS  AgentCore Runtime <name>: READY on platform V1
FAIL  AgentCore Runtime <name>: platform V2, not the pinned V1. Fix: in the box's terminal, before Lab 3, run uv run python scripts/deploy_agentcore.py deploy; it updates the runtime in place on V1
FAIL  AgentCore Runtime <name>: status UPDATING, not READY
FAIL  AgentCore Runtime <name>: could not read the platform version (<reason>)
FAIL  AgentCore Runtime platform check did not finish: <last line>
```

"Could not read" covers a runtime that names no platform, a failed `GetAgentRuntime` and a
runtime ARN missing from the box's `.env`. A READY runtime then gets a second line, under
its role's name, for its endpoint, models and image. Only this record judges the
platform: bootstrap's connect step and a participant's deploy never fail on it. Every
deploy names `V1`, so the Lab 3 deploy also moves a runtime found on another platform
back in place. Run it before Lab 3 starts: from then on it deploys the participant's code.

## Read the records

Use each event account's Ops credentials: in the facilitator console, **Teams** >
**Access AWS account (Ops role)** > copy.

One account, with the credentials in your shell:

```bash
uv run scripts/event_readiness.py            # the latest record
uv run scripts/event_readiness.py --live     # record again now, through SSM Run Command
```

Every account: save one file per account in a Git-ignored folder, such as
`.local/readiness/`, mode 0600, with a name ending in `.env`. The script reads only
`*.env` files, so a folder of other names reads `0 of 0 ready`. Paste the console's
block as it is, then add the Region on a line of its own. The copied block has no final
newline, so write the line with `printf '\nAWS_DEFAULT_REGION=us-east-1\n' >> FILE`,
not `echo ... >> FILE`. The script parses the files and never sources them, refuses a
file that group or others can read, and prints account IDs to the terminal only. Delete
the folder when you are done.

```bash
uv run scripts/event_readiness.py --accounts .local/readiness
uv run scripts/event_readiness.py --accounts .local/readiness --live
```

```text
Account        Region      Instance              Recorded (UTC)     Status
<12 digits>    us-east-1   i-0123456789abcdef0   2026-12-01 06:40   ✅ READY FOR LAB 1
<12 digits>    us-east-1   i-0fedcba9876543210   2026-12-01 06:41   ❌ Memory: status CREATING
<12 digits>    us-west-2   -                     -                  ❌ setup failed: BootstrapWaitCondition: ...
1 of 3 ready
```

CloudFormation decides before the record. A box can write its record before a later
resource fails the stack, so a ✅ also needs the account's root stack to have finished
without a rollback (`CREATE_COMPLETE` or `UPDATE_COMPLETE`).

A ✅ also needs the participant's browser path to answer at that moment, through
CloudFront, the way a participant's browser reaches it. The laptop fetches the storefront
page and `/api/readiness` (which reaches Aurora) from the stack's `MosaicURL`, and the
Code Editor's own `/healthz` from the domain of `CodeEditorURL`. None of them needs a token
or a sign-in, so no account is claimed, and all three only read: no model call, no row
written. `CodeEditorURL` carries the editor's connection token, so the script keeps only
its domain and never prints either URL. Only an `https` URL on a `*.cloudfront.net` host,
with no user name, password or port, is ever fetched, and a redirect is the answer, never
followed. Readiness gets three tries, the page and the editor two, 5 seconds apart, each
with a hard 20-second deadline that also bounds the DNS lookup, and an account spends at
most 60 seconds on them. A fleet in which nothing answers therefore takes about a minute
per eight accounts.

A record also has to belong to this stack and its own box. It must have reached
CloudWatch (by CloudWatch's clock, not the box's) after the stack's current form began:
its creation, or its last update for a stack in an `UPDATE_*` state. CloudFormation stamps
an update's start, and Workshop Studio updates each stack once right after creating it, so
only an updated stack moves that time. The record must also come from the instance the
stack's nested Code Editor stack created (its `EditorInstanceId` output), and that
instance must be running. `--live` targets the same instance. After an in-place update,
every good account reads `⚠️ no record (the newest record predates this stack)` until its
box records again: run `--live` before participants arrive, which is what it is for.

The box's checks run as the Linux user `participant`, in the repository with its `.env`,
which is how the Code Editor terminal runs. They do not sign in to Workshop Studio as a
participant. Only a participant joining the event claims a team: on the DAT410 test event
of 22 November, a team read with the Ops role (console sign-in included), read mode and
`--live` still showed no participant afterwards.

A status is one of:

- `✅ READY FOR LAB 1`;
- `❌` and the first failing check;
- `❌ setup failed:` and CloudFormation's first failure, for a failed or rolled-back
  root stack, whatever the record says;
- `❌ storefront does not answer (<why>)` or `❌ Code Editor does not answer (<why>)`,
  with an HTTP status, `database not ready`, `no usable <output>` or the error's name;
- `❌ Code Editor instance not running`, `⚠️ no record (the newest record predates this
  stack)`, `⚠️ no record (the newest record is from another instance)` and `⚠️ cannot read:
  NoEditorInstanceIdOutput` when the record cannot speak for this stack's own box;
- `⚠️ setup still running (<status>)` for a READY record while the root stack is still
  being created or updated, `⚠️ setup not complete (<status>)` for any other unfinished
  state (a stack being deleted, for example), and `⚠️ no workshop stack in this Region`
  when no root stack is found (with no record: `⚠️ no record (no workshop stack in this
  Region)`);
- `⚠️ STALE` for a record older than `--max-age-hours` (default 24);
- `⚠️ no record` with the stack's status (for example, still creating);
- `⚠️ lab in progress (Lab N), not rechecked`;
- `⚠️ same account as <file>` for a second file of an account already listed, so the
  count never includes a team twice;
- `⚠️ cannot read:` with the AWS error code, such as `ExpiredToken`, or the file's
  problem: `DuplicateKey` (two values for one key, such as two blocks pasted into one
  file), `InvalidRegion` (the value is never printed), `MissingRegion`,
  `MalformedRecord` (a record whose time is missing, has no zone or lies in the
  future) or `TooManyLogEvents` (more than 100 pages in the 14 days read).

Rows follow file-name order, and at most eight accounts are read at once. Every cell is
printed with control, format (bidi overrides included), private-use and unassigned
characters replaced by `?`, so nothing in a record or a CloudFormation reason can rewrite
the terminal or reorder the row.

The command exits 0 only when every row is ready and there is at least one row, 1
otherwise, and 2 on a usage error. Without `--live` it only reads: CloudWatch
`FilterLogEvents` on the readiness group (never `DescribeLogStreams` or `GetLogEvents`),
and CloudFormation's stack descriptions for an account with no record. `--live` sends
`mosaic-readiness-record --live` with `ssm:SendCommand` to the instance the newest record
names, or else to the running Code Editor host that `ec2:DescribeInstances` finds by the
editor launcher's tag. It follows the command with `GetCommandInvocation` and reads the
new record from CloudWatch, waiting up to four minutes. A box that is not ready makes
the command fail but still writes its record, so the record decides the row.

`--live` rechecks a box only before its participant starts. The box first reads each
lab's state, as `lab_state.py status` does. Once any lab has started, Lab 1 included
(Getting started runs `start --lab 1`), or when the state cannot be read, it opens no
database session, writes no record and prints `⚠️ lab in progress (Lab N), not
rechecked` with the previous record's time. During the session, read the records without
`--live`.

The Ops role was proven for `logs:FilterLogEvents` and `ssm:SendCommand` on a DAT416 test
event. Prove `ssm:GetCommandInvocation`, `ec2:DescribeInstances` and the CloudFormation
reads on a DAT410 dry run before relying on them.
