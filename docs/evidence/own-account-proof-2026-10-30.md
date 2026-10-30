# Own-account proof, 30 October 2026 (built in us-east-1, deployed in us-west-2)

A maintainer ran [Run Mosaic in your own account](../run-in-your-own-account.md) end to
end in a personal AWS account (not a Workshop Studio account), from the public source
repository, with no access to the workshop's published assets. The account, bucket and
key identifiers are withheld. The proof branch `own-account-proof-2026-10-30` holds the
contracts this build produced; it is never merged, so `main` keeps the contracts of the
bundle published for events.

Source revisions: the staging environment and the first catalog steps ran at
`da5d84aa`; the build resumed at `d5b2ce82`, `9cf5bffb` and `7252abd6` as defects were
fixed. The successful stack deployed from the proof branch at `a0bbcfc8` (own-account
`04e0949f` plus the rebuilt contracts), release `7d33eb9f06b79b47`; the teardown used
`5911c105`.

## Catalog build

| Step | Seconds | Note |
|---|---:|---|
| staging up | 976 | 16 min 16 s to `CREATE_COMPLETE` (third attempt; see defects 1 and 2) |
| fetch | 446.2 | three metadata files and five question files, about 50 MB/s |
| prepare | 717.1 | 553,911 products selected; identical to the committed contract |
| embed | 24,047.1 | 553,911 products, 10,665 batches, 276,826,378 input tokens, three Regions at 300,000 tokens per minute each |
| schema | 1.3 | `make db-bootstrap-schema` into the empty staging cluster |
| stage | 292.2 | records and vectors loaded, completeness verified |
| evidence | 458.6 | the resumed run; review scans streamed about 60 GB |
| export | 216.1 | archive of 2,521,919,722 bytes in three parts |
| restore-check | 1,168.8 | restore 1,104.1 s; HNSW index 101.6 s with 7 workers |
| vocabulary | 187.4 | 2,200,149 and 2,251,580 rows |
| upload | 21.7 | bundle and contracts to the private bucket |
| staging down | 756 | 12 min 36 s to `DELETE_COMPLETE` |

Step time in all: 7 h 39 min. Wall-clock from the first build command to the summary:
8 h 25 min, including three fix-and-resume cycles. The selection identity check passed
on the first run (same products and catalog hash as the committed contract). Review and
question sample counts differ from the committed contract, as the page says they will:
349,151, 79,459 and 19,258 reviews and 60,751 questions, against 351,134, 53,464, 14,022
and 80,111.

## Defects found by the proof and fixed

1. The account held 6 VPCs against a quota of 6 in us-east-1, so the staging stack rolled
   back; the tool now checks VPC and Elastic IP headroom and names a nested stack's
   failure (`879b5e26`). A raised quota was visible in Service Quotas about fifteen
   minutes before EC2 enforced it (`da5d84aa`).
2. The builder role could not read the embedding inference profile; the grant and a
   `staging update` subcommand were added (`cd62503a`).
3. The stage step met an empty cluster (`type "vector" does not exist`): only the later
   restore-check installed the schema. A `schema` step now precedes `stage`, and the
   preflight connects to the database once and confirms the four extensions are
   available before any step (`d5b2ce82`).
4. The Home_and_Kitchen review scan got HTTP 429 from the source host; the eight-attempt
   backoff gave up in about ninety seconds and the error could not cross the worker
   process boundary, so the run reported a pickling error. Twelve attempts honouring
   Retry-After and a plain error naming the range (`9cf5bffb`).
5. A rerun scanned every finished review part a whole part-length past its boundary;
   parts now resume from their checkpoints (`7252abd6`).
6. GitHub serves a commit to the builder only by its full hash; the page says so.
7. The account's State Manager association patched and rebooted every new Code Editor host
   four minutes after launch, killing the inline bootstrap (see Deployment); the bootstrap
   now runs as a service that resumes after a reboot (`f5b05858`, `04e0949f`).
8. Both teardowns stopped on the runtime security group, held by AgentCore's network
   interface for hours, before the database and VPC were deleted (see Teardown); teardown
   now deletes everything billable and finishes on a second run (`5911c105`).

## Transaction Search restore, proven alone first

The stack turns on CloudWatch Transaction Search, an account-wide setting per Region.
Four runs of the custom resource alone, in a Region where the setting was off,
measured: the destination switch stays `PENDING` for about six minutes and refuses
updates meanwhile; an indexing-rule update sent during that time returns success and
never applies; X-Ray creates an empty `default` stream in each group it makes. The
resource now waits for the switch to settle before setting the indexing percentage and
before switching back, keeps a group that holds any event, and removes only a group it
created that holds none (`d55c3aee`). Measured: create 425 s including the settle, delete
32 s, the Region back as found about six minutes later; with a real segment in
`aws/spans`, that group was kept and the empty one removed. The full-stack proof of the
restore ran in us-west-2 (separate record).

## Deployment: the patch-on-launch reboot, and the bootstrap that resumes

The first two deploys, in us-east-1 and us-west-2, failed about four minutes after the
Code Editor host launched. The account's Systems Manager State Manager association runs
`AWS-RunPatchBaseline` (install, every instance, immediately on launch, reboot if needed)
on each new instance; the patch finished and rebooted the host while the bootstrap ran. In
us-west-2 the UI build died of a hangup and the bootstrap reported a failure, so the stack
rolled back (which, as a side effect, ran the Transaction Search restore through the full
stack and left the Region as found). In us-east-1 the bootstrap died silently and the
wait condition timed out after two hours. A third host kept without rollback showed the
sequence in its journal: boot, patch run, reboot four minutes later, cloud-init finishing
in six seconds with user-data not rerun, the host idle. The Studio event host of the same
day used the same AMI and passed, because Workshop Studio accounts carry no such
association; a customer account that patches on launch would have failed the same way.

The bootstrap now runs as `mosaic-bootstrap.service`, a unit the loader installs and
starts, which resumes at the next boot until a completion marker exists, with one marker
per finished phase and every phase safe to rerun (`f5b05858`). A reboot is told apart
from a failure by the system's state, not by an exit code. A first deploy of it failed at
template validation, because Fn::Sub rejects bash brace expansions anywhere in user-data
(`04e0949f`, with a test that refuses them).

The live run, us-west-2, stack `mosaic-proof3-usw2` from the proof branch at `a0bbcfc8`
(release `7d33eb9f06b79b47`), created without rollback so the host could be inspected:

| Time (UTC) | Event |
|---|---|
| 17:50:18 | Stack creation starts |
| 18:01:02 | VPC (3 min 2 s) and Aurora (7 min 29 s) complete |
| 18:07:12 | The bootstrap unit starts on the new host |
| 18:10:55 | The patch association reboots the host during the UI phase; the unit stops quietly |
| 18:11:15 | The unit starts again and skips packages, source, secrets and image |
| 18:33:42 | The catalog phase completes (22 minutes) |
| 18:34:12 | Every acceptance check passes; SUCCESS is signalled |
| 18:37:13 | `CREATE_COMPLETE`, 46 min 55 s after the start |

The stack turned on Transaction Search in us-west-2, with every span indexed (the
percentage applied only after the destination switch settled, which the fix made it wait
for).

## Labs on the self-built catalog

A participant run over Systems Manager, as the participant user, following the guide's
pages: all three labs passed with no environment failure and no answer tools used. Every
count, position and score the guide quotes for Labs 1 and 2 was identical on the rebuilt
vectors (Lab 1: `0|0|50|50|0` broken, fuzzy matching rank 1, `0|1|49|50|1` repaired, the
Logitech at combined and final position 1; Lab 2: `10|50|2|` broken, both monitors at
0.0164, `10|50|43|21` repaired, the ViewSonic from combined 21 to final 5, the Acer at #6
with reranking). The one number that moved is the Lab 2 settings comparison: the current
settings let 129 exact matches reach reranking against 128 on the published bundle, and a
shortlist of 75 reaches 145 on both, so its row reads +16 (15 better, none worse) against
+17 (16 better). Lab 3: the deploy took 1:09 (usually 1:11); Alex's setup request was
answered and grounded with six citations, a listing and a review for each product; the
100W follow-up was grounded on the listing's 90W; the completion check passed and
`lab_state.py status` read `Lab 3: SOLVED`. `make validate-evals` passed: 17, 65 and 2,081
judged targets and independent relevance corpora of 24 and 404 queries.

## Teardown

`teardown --delete-bucket` in us-west-2 started at 19:22:25 UTC. The runtimes were deleted
at 19:22:34 and 19:24:43, and after 24 minutes 51 seconds the stack stopped in
`DELETE_FAILED`: every resource of the Code Editor stack was gone except
`RuntimeSecurityGroup`, which "has a dependent object", an AgentCore-managed network
interface (`InterfaceType` `agentic_ai`, tag `AmazonBedrockAgentCoreManaged`). The root had
not reached the database or VPC stacks, so Aurora and the NAT gateway were still running.
The us-east-1 stack had stopped the same way after its rollback; its interface was still in
use more than four hours after its runtimes were deleted (15:37 and 15:41 UTC), and a user
cannot detach it ("You are not allowed to manage 'ela-attach' attachments"). AWS documents
up to 8 hours on the AgentCore VPC page.

A second delete with `RetainResources` set to the two root resources that hold the
interface's security groups (`CodeEditorStack` and `DatabaseClientSecurityGroup`) removed
the database and the NAT gateway in both Regions (us-east-1: 27 minutes); what remains is
the VPC, a private subnet, the two security groups and AWS's interface, none of which bills.
`teardown` now does this itself and exits `NOT FINISHED` with the interface's ID
(`5911c105`); a poller runs `teardown` again in each Region once AWS removes the interface.
[final deletion time: to be added when the interfaces are released]

Transaction Search came back through the full stack: the custom resource's delete note was
"restored indexing, destination, policy, kept aws/spans, kept
/aws/application-signals/data", and the Region read destination `XRay` `ACTIVE`, indexing
0, no Mosaic policy. Both groups were kept because Lab 3's traces had landed in them; they
remain for the owner to keep or delete.

## Cost

The embedding is the one large per-build charge: the bill so far shows Cohere Embed v4
input tokens at $0.12 per million in each of the three Regions, so the build's 276,826,378
tokens cost about $33. Everything else is billed by the hour: the staging environment ran
from 03:53 to 12:52 UTC (about 9 hours) and the successful workshop stack from 17:50 UTC
until teardown's first pass ended at 19:47 (about 2 hours). The failed us-east-1 stack and
its Aurora cluster ran from 13:23 to about 19:47 UTC before the retained delete removed
them; a customer whose account does not patch on launch does not pay for that.
