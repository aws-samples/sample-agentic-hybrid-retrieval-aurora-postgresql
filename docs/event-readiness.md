# Event readiness

Each event box records whether it is ready for the event. A facilitator reads those
records from a laptop, for one account or for every account at once. DAT416 and DAT432
use the same command and the same table.

## The record

Bootstrap writes the record twice at most:

- After its acceptance gate passes and CloudFormation has heard SUCCESS. The record runs
  under its own 120-second cap, so it cannot hold the stack.
- When a bootstrap phase fails, before CloudFormation hears FAILURE. That record names the
  failing phase. A failure before the repository's environment exists leaves no record;
  the laptop then prints CloudFormation's reason instead.

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
- **State before participants start:** Lab 1 `BROKEN`, Labs 2 and 3 `NOT STARTED`. Once
  a participant starts a lab, this line becomes information and no longer decides
  readiness.

The checks that need a write ran once in the bootstrap gate: Lab 1's broken search, a
reranked search, a Gateway search with evidence, the Session Memory round trip, Claude
Code's answer, the mission and evaluation checks, and Lab 2's validation. The record lists
each with the time the gate passed.

An absence counts as ready only after a positive control. Fuzzy matching must find the
Logitech (1492978) for both Lab 1's typo and the exact ID before the gate's "Logitech
absent" proves the fault. A runtime that reports no platform version fails, because a
missing value is not `V1`. A record in which no check passed is not ready.

## Read the records

Use each event account's Ops credentials: in the facilitator console, **Teams** >
**Access AWS account (Ops role)** > copy.

One account, with the credentials in your shell:

```bash
uv run scripts/event_readiness.py            # the latest record
uv run scripts/event_readiness.py --live     # record again now, through SSM Run Command
```

Every account: save one file per account in a Git-ignored folder, such as
`.local/readiness/`, mode 0600. Paste the console's block as it is and add an
`AWS_DEFAULT_REGION=<region>` line. The script parses the files and never sources them,
refuses a file that group or others can read, and prints account IDs to the terminal
only. Delete the folder when you are done.

```bash
uv run scripts/event_readiness.py --accounts .local/readiness
uv run scripts/event_readiness.py --accounts .local/readiness --live
```

```text
Account        Region      Instance              Recorded (UTC)     Status
<12 digits>    us-east-1   i-0123456789abcdef0   2026-12-01 06:40   ✅ READY FOR LAB 1
<12 digits>    us-east-1   i-0fedcba9876543210   2026-12-01 06:41   ❌ Memory: status CREATING
<12 digits>    us-west-2   -                     -                  ⚠️ no record (ROLLBACK_COMPLETE: ...)
1 of 3 ready
```

A status is one of `✅ READY FOR LAB 1`, `❌` and the first failing check, `⚠️ STALE` for a
record older than `--max-age-hours` (default 24), `⚠️ no record` with the stack's status
and first failure, or `⚠️ cannot read:` with the AWS error code, such as `ExpiredToken`.
Rows follow file-name order, and at most eight accounts are read at once.

The command exits 0 only when every row is ready and there is at least one row, 1
otherwise, and 2 on a usage error. Without `--live` it only reads: CloudWatch
`FilterLogEvents` on the readiness group (never `DescribeLogStreams` or `GetLogEvents`),
and CloudFormation's stack descriptions for an account with no record. `--live` sends
`mosaic-readiness-record --live` with `ssm:SendCommand` to the instance the newest record
names, or else to the running Code Editor host that `ec2:DescribeInstances` finds by the
editor launcher's tag. It follows the command with `GetCommandInvocation` and reads the
new record from CloudWatch, waiting up to four minutes. A box that is not ready makes
the command fail but still writes its record, so the record decides the row.

The Ops role was proven for `logs:FilterLogEvents` and `ssm:SendCommand` on a DAT416 test
event. Prove `ssm:GetCommandInvocation`, `ec2:DescribeInstances` and the CloudFormation
reads on a DAT410 dry run before relying on them.
