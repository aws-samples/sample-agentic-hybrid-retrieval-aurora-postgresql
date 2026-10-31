# Run Mosaic in your own account

This page deploys the Mosaic workshop environment into an AWS account you own,
so you can work through the three labs in the workshop guide without an AWS event.
You build the product catalog yourself, publish the deployment files to a private
bucket in your account, and create one CloudFormation stack. You delete everything
when you finish.

This is the only supported way to run Mosaic outside an AWS-run event. Facilitators
do not support it, and every charge is yours.

## 1. What you get and what it costs

The stack creates one environment for one person. Each resource below is declared
in the CloudFormation templates under `deploy/cloudformation/`.

| What | Detail |
|---|---|
| Amazon Aurora PostgreSQL | A new encrypted cluster, engine version 18.3, with one writer instance, `db.r8g.2xlarge` by default (`db.r8g.xlarge` and `db.r8g.4xlarge` are also allowed). It holds the catalog, vectors and audit records. |
| Code Editor host | One `c6g.2xlarge` EC2 instance by default with a 50 GB volume, in a private subnet with no public IP. It runs Code Editor, the Mosaic API and the storefront. An editor launcher (a Lambda function) tries other allowed instance types and zones if the first has no capacity. |
| Networking | A new VPC with public and private subnets and one NAT gateway, so the host can reach AWS APIs and download packages. |
| Amazon CloudFront | Two distributions, one for Code Editor and one for Mosaic, reaching the host through CloudFront VPC origins. In `us-east-1` an AWS WAF web ACL is attached to them. Other Regions get no web ACL, because CloudFront-scoped WAF resources exist only in `us-east-1`. |
| Amazon Bedrock AgentCore | A Runtime for the Retrieval agent, a Runtime for the SQL tools, a Gateway that exposes the tools, and a Memory resource. |
| Amazon ECR and AWS KMS | A repository for the runtime container image, and account-local KMS keys. |
| AWS Lambda | Four functions: the editor launcher and three helpers for credentials, tracing and runtime logging. |
| Amazon CloudWatch | Log groups, and AgentCore Observability for Lab 3's agent traces, which is enabled by default (`AgentObservability`). |
| Secrets | AWS Secrets Manager secrets for generated credentials. |
| Builder host (temporary) | One `c7g.2xlarge` EC2 instance with a 300 GB EBS volume, which builds the catalog bundle. |
| Staging database (temporary) | One Aurora PostgreSQL cluster with a `db.r8g.2xlarge` writer, which the build loads and verifies against. |

The labs also call Amazon Bedrock for query embeddings (Cohere Embed v4), reranking
(Cohere Rerank 3.5) and the agent model (Claude Sonnet 5.5).

Building the catalog adds the two temporary resources in the last rows of the table.
Section 4 creates them (step 3) and deletes them (step 6).

The build downloads a lot of data. About 19 GB of product metadata is downloaded once, and
about 60 GB of review files are read twice, so expect about 120 GB of transfer for them. The
finished bundle is about 2.5 GB. These sizes come from the pinned source files in
`scripts/catalog/fetch_catalog_metadata.py` and `scripts/catalog/fetch_catalog_reviews.py` and
from `db/config/real-catalog-cache.json`. In the proof run the builder held 15 GB on its
300 GB disk after the downloads and the embeddings, and the review scans streamed about 60 GB
more without storing it (Electronics 22.6 GB, Home_and_Kitchen 31.4 GB, Office_Products
5.8 GB). The metadata downloads took 7.4 minutes at about 50 MB/s. The evidence step,
which runs the review scans, took 7.6 minutes in its final run, which resumed earlier runs
stopped by the source host's rate limit; an uninterrupted run was not measured.

**Cost.** This page gives no prices, because they change. Read the current rates:

- [Amazon Aurora pricing](https://aws.amazon.com/rds/aurora/pricing/)
- [Amazon Bedrock AgentCore pricing](https://aws.amazon.com/bedrock/agentcore/pricing/)
- [Amazon Bedrock pricing](https://aws.amazon.com/bedrock/pricing/) (embeddings, reranking and the agent model)
- [Amazon EC2 pricing](https://aws.amazon.com/ec2/pricing/on-demand/)
- [Amazon CloudFront pricing](https://aws.amazon.com/cloudfront/pricing/)
- [NAT gateway pricing](https://aws.amazon.com/vpc/pricing/) (listed under NAT Gateway)

These run continuously, whether or not you are using the labs: the Aurora writer, the
Code Editor host (`c6g.2xlarge` with its 50 GB volume), and the NAT gateway with its public
IPv4 address. The staging database and the builder with its 300 GB volume run only between
steps 3 and 6 of section 4. Delete the stack when you are done (section 6).

Measured totals from the proof run:

- Catalog build: 7 hours 39 minutes of step time in the proof run (three embedding
  Regions, 12 workers), 6 hours 41 minutes of it embedding
- Catalog build, Bedrock embedding tokens: 276,826,378 input tokens for 553,911 products in
  10,665 batches
- Stack creation time: 46 minutes 55 seconds in the proof run, in us-west-2, including the
  host restoring the catalog (22 minutes) and one reboot by the account's patch-on-launch
  association
- Cost of one build, one lab session and teardown: the embedding is the one large
  per-build charge, about $33 at the rate the proof account was billed for Cohere Embed v4
  input tokens ($0.12 per million). The rest is billed by the hour at your Region's
  prices: the staging environment (a c7g.2xlarge builder and an Aurora cluster) ran for
  about 9 hours, and the workshop stack about 2 hours from creation through the labs to
  the end of teardown's first pass

## 2. Before you start

**An account you may use freely.** Use a sandbox or personal account. You need
administrator rights: the stack creates IAM roles, KMS keys, CloudFront
distributions and Bedrock AgentCore resources. The workshop's own participant policy
is much narrower than what the stack needs to create these resources.

**A Region.** Use `us-east-1`. It is the Region where the workshop is validated end
to end. `us-west-2` also deploys, with two differences you should expect:

- It has no WAF web ACL on the CloudFront distributions.
- Cohere Embed v4 has no on-demand access in `us-west-2`. The workshop uses the
  `us.cohere.embed-v4:0` inference profile, which serves the call from another Region.
  A Bedrock impairment in that Region can therefore fail searches in a `us-west-2` stack.

**Bedrock models.** The workshop invokes these three:

| Model ID | Used for |
|---|---|
| `global.anthropic.claude-sonnet-5-5` | The Retrieval agent and Claude Code in Code Editor |
| `us.cohere.embed-v4:0` | Query and catalog embeddings |
| `cohere.rerank-v3-5:0` | Reranking |

The Bedrock [Request access to models](https://docs.aws.amazon.com/bedrock/latest/userguide/model-access.html)
page says what is needed:

- In commercial Regions, many models are enabled on first use. There is no access
  request to submit.
- The first invocation of a third-party model starts a subscription in the
  background, and that needs the IAM actions `aws-marketplace:Subscribe`,
  `aws-marketplace:Unsubscribe` and `aws-marketplace:ViewSubscriptions`, and a valid
  payment method on the account. Cohere models are third-party models.
- For Anthropic models, complete the first-time use case form once, before the first
  call. Choose an Anthropic model in the Bedrock console's **Model catalog** and open
  it in the playground. If your organization's management account has already
  submitted the form, you can skip this.
- A missing prerequisite makes the call return `AccessDeniedException` until you fix it,
  and then for up to 2 more minutes while the subscription finishes. The subscription
  itself can take up to 15 minutes, during which calls may still succeed.
- The Anthropic form asks for a description of your intended use and a website URL. If you
  have no company website, a personal portfolio, GitHub profile or project URL is accepted.
  The model agreement can sit in a pending state, during which calls keep returning
  `AccessDeniedException`, until AWS sends you an email. Read its status with
  `GetFoundationModelAvailability` instead of waiting.

**Service-linked roles.** The stack uses two service-linked roles, `rds.amazonaws.com` and
`vpcorigin.cloudfront.amazonaws.com`. You do not create them. The `check` command only
reports a missing one as a failure, and `staging up` and `deploy` create it before they
create the stack.

**Quotas.** Check these in Service Quotas before you start:

- Amazon EC2: the builder (`c7g.2xlarge`, 8 vCPUs) and the Code Editor host
  (`c6g.2xlarge`, 8 vCPUs) both count against the "Running On-Demand Standard instances"
  quota. Step 6 deletes the builder before step 10 creates the host, so they never run
  together and you need room for 8 vCPUs at a time.
- Amazon Bedrock: tokens per minute for Cohere Embed v4 in your Region. This bounds how
  fast the catalog build can embed products. The proof run had 300,000 tokens per minute for
  `us.cohere.embed-v4:0` in each of us-east-1, us-east-2 and us-west-2 and paced itself at
  255,000 per Region, 85% of that.

If you raise the VPC or Elastic IP quota just before deploying, EC2 can keep enforcing the old
value for a while after Service Quotas shows the new one, and `staging up` then rolls back on
the VPC with "The maximum number of VPCs has been reached". Run `staging down`, wait a few
minutes and try again.

**Tools on your machine.**

- git
- [uv](https://docs.astral.sh/uv/), which installs the Python 3.13 the repository pins
- AWS CLI v2, signed in to the account (`aws sts get-caller-identity` prints it)
- The [Session Manager plugin](https://docs.aws.amazon.com/systems-manager/latest/userguide/session-manager-working-with-install-plugin.html) for the AWS CLI, which step 4 of section 4 needs to open a shell on the builder

**A public fork.** The Code Editor host clones the repository without credentials,
so the repository it clones must be public. Fork
`aws-samples/sample-agentic-hybrid-retrieval-aurora-postgresql` on GitHub into your
own account and keep the fork public.

## 3. Prepare the data

The catalog is not stored in this repository, and it is not redistributed. You build
it from public sources and from Bedrock embeddings. The build produces a
hash-pinned bundle: the product archive in parts of at most 900,000,000 bytes, and two
vocabulary files. The proof run's bundle held 553,911 products in a 2,521,919,722-byte
archive, split into three parts, plus two vocabulary files of 11.7 MB and 12.2 MB.

**What goes in.**

- Product metadata and reviews from the [Amazon Reviews 2023](https://amazon-reviews-2023.github.io/)
  dataset (Electronics, Home and Kitchen, Office Products), downloaded from its Hugging Face
  repository at a pinned revision and checked against pinned SHA-256 values. Check that
  dataset's own terms before you use it.
- Product questions from the Amazon PQA dataset (monitors, headphones, headsets, chairs),
  licensed CDLA-Permissive-1.0.
- Embeddings of each product's text from Cohere Embed v4 (`us.cohere.embed-v4:0`,
  1,024 dimensions) on Amazon Bedrock. These calls are billed, and interrupted or
  retried calls can be billed too.

**What the build does.** `make catalog-bundle` runs eleven steps in order: fetch, prepare,
embed, schema, stage, evidence, export, restore-check, vocabulary, upload and summary. Before
any step, it connects to the staging database once and checks that the cluster can install
pgvector and the other extensions, so a database problem stops the run before hours of
embedding are spent. The `schema` step installs the extensions, tables and functions into
the empty staging database, exactly as the event bootstrap does. Reviews and
questions are filtered against the staged catalog, so they come after `stage`. The
`restore-check` step restores the exported archive into the staging database and runs the
bootstrap verification. It proves the parts join to the contract hash and that the indexes
and checks work from that archive. It does not prove that the loader inserts the archive's
vectors into an empty database, because the staging database already holds them.

**What comes out.**

- `real-catalog/` with the archive parts and the two vocabulary files, uploaded to your
  private bucket.
- Two contract files that pin them by size and SHA-256: `real-catalog-cache.json` and
  `corpus-vocabulary-cache.json`. The stack refuses to load a bundle that does not match the
  copies committed to your fork.

The builder never pushes to git. After the upload step you delete the staging environment
and pull the two contract files from the bucket into your clone (section 4, steps 6 and 7).

**Resuming.** Every step resumes from its own checkpoints: metadata ranges, embedding
batches and staged batches. Running the wrapper again continues after the last completed
step. A failing command stops the run, prints the command and says to run it again.
A mismatch between your selection and the expected one stops the run before any embedding
is spent. If you fix the source in your fork while the staging environment is up, push the
fix and bring the builder's checkout to that commit before you run the wrapper again; the
finished steps and their saved embeddings are kept. GitHub serves a commit by its full
40-character hash only, so an abbreviated hash fails with "couldn't find remote ref":

```bash
sudo -u builder -H git -C /workshop/sample-agentic-hybrid-retrieval-aurora-postgresql \
  -c credential.helper= fetch --depth 1 origin <full commit hash>
sudo -u builder -H git -C /workshop/sample-agentic-hybrid-retrieval-aurora-postgresql \
  checkout -q FETCH_HEAD
```

**Embedding speed.** The build defaults to one Region and 4 workers. The pinned source
documentation records one earlier build at about 23,422 new embeddings an hour with one
Region and about 79,716 an hour with three Regions, 12 workers and adaptive pacing. Those
runs embedded different texts and are not a controlled benchmark. The three-Region
figure used applied quotas of 300,000 tokens per minute in each Region, which was the event
account's quota. Your account's default is not measured. To use the three Regions, pass
them to the build command in step 5 of section 4. The proof run's steps on a fresh account,
with three Regions and 12 workers, took 7 hours 39 minutes in all: fetch 7.4 minutes, prepare
12.0 minutes, embed 6 hours 41 minutes, schema and stage 4.9 minutes, evidence 7.6 minutes
(its final, resumed run),
export 3.6 minutes, restore-check 19.5 minutes (restore 18.4 minutes, of which the HNSW index
1.7 minutes), vocabulary 3.1 minutes, upload 22 seconds.

**What changes in a rebuild.** The selected products and their text are deterministic, so
the contract should again record 553,911 products and 10,665 embedding batches; if it does
not, treat that as a failure to investigate. The archive, its parts and the vocabulary
files carry a time stamp in their gzip headers, so their hashes differ on every build, and
the two contract files must be committed after each one. Review and question counts
(351,134, 53,464 and 14,022 review samples and 80,111 question samples in the contract the
workshop was validated on) may differ in your build. The evidence step prints a boxed WARN
listing every count that differs from the shipped contract. That is expected, and those
counts become your new contract's counts.

Cohere Embed v4 does not return identical vectors for the same text, so your vectors
differ slightly from the ones the workshop was validated with. In the proof run every
count, position and score the guide quotes for Labs 1 and 2 came out identical on the rebuilt
vectors, all three labs passed, and `make validate-evals` passed. The one number that moved
is the Lab 2 settings comparison: Mosaic's current settings let 129 exact matches reach
reranking, one more than the guide's screenshot shows (128), and a shortlist of 75 reaches 145
on both, so its row reads +16 with 15 requests better where the screenshot shows +17 and 16.

## 4. Deploy

Every `deploy.py` subcommand takes `--profile` and `--stack-name`. `--region` falls back to
`AWS_REGION`, then `AWS_DEFAULT_REGION`, then the profile's Region. The steps below name the
Region and use the default profile and stack names. `staging up` and `deploy` refuse to run
if a stack with the same name already exists. The private bucket is named
`mosaic-own-account-<account>-<region>` unless you pass `--bucket`. `staging up` and
`publish` create it if it is missing and tag it `MosaicOwnAccount=true`; they refuse an
existing bucket without that tag. Add `--dry-run` to a command to see what it would do
first; on a working tree with uncommitted changes it warns instead of refusing.

Steps 1 to 4 and 6 to 10 run on your machine and step 5 runs on the builder.

**Step 1.** Clone your fork on your machine. Replace `YOUR-ACCOUNT` with your GitHub user
name.

```bash
git clone https://github.com/YOUR-ACCOUNT/sample-agentic-hybrid-retrieval-aurora-postgresql.git
```

Then enter it.

```bash
cd sample-agentic-hybrid-retrieval-aurora-postgresql
```

**Step 2.** Check your account against the requirements in section 2. The command changes
nothing. It prints one line per requirement, makes a small billed call to each of the three
Bedrock models, tries to clone your public fork without credentials, and exits with an error
if any line is marked as failed. Fix every failed line before you continue.

```bash
uv run python deploy/own-account/deploy.py check --region us-east-1
```

**Step 3.** Create the staging environment: the private bucket, a temporary Aurora
cluster and the builder instance. It also runs the clone check again. This is billed from
now until step 6.

```bash
uv run python deploy/own-account/deploy.py staging up --region us-east-1
```

Staging creation time: 16 minutes 16 seconds in the proof run (the VPC, the Aurora cluster
and the builder).

**Step 4.** Print the Session Manager command that opens a shell on the builder, then
copy it into your terminal and run it. It looks like
`aws ssm start-session --target i-0123456789abcdef0 --region us-east-1`, with your
instance ID.

```bash
uv run python deploy/own-account/deploy.py staging status --region us-east-1
```

**Step 5.** In the builder shell, start the catalog build. The wrapper runs as the
builder user inside the checkout with the database settings loaded, and writes its log to
`/workshop/catalog-bundle.log`. The build runs for hours and keeps going if your session
closes. Its last step before the summary uploads the bundle and the two contract files to
your bucket; the builder reads the bucket name from `/etc/mosaic-own-account.env`.

```bash
mosaic-catalog-bundle
```

To watch progress, or to look again after a closed session, follow the log.

```bash
tail -f /workshop/catalog-bundle.log
```

If the build stops or you close the session, run `mosaic-catalog-bundle` again: it
resumes from the last completed step. The wrapper refuses to start a second build while one
is running. Expected duration: about 7 hours 40 minutes with three Regions (section 3), most
of it embedding.

The build has ended when the last lines of the log are the summary. It prints
"Commit these two contract files:" and then "On your laptop, in your fork, in this order:".
Once those lines appear, step 6 no longer refuses.

To use three Regions for the embeddings, give the wrapper the options, which it passes
to the build.

```bash
mosaic-catalog-bundle --regions us-east-1 us-east-2 us-west-2
```

**Step 6.** Back on your machine, delete the staging cluster and the builder. They
have done their job, so stop paying for them. The bucket and its contents stay. The
command refuses to run, unless you add `--force`, when the two contract files or the five
bundle objects are missing from the bucket, because the build would be lost. It then lists
what the staging environment leaves behind (see section 6).

```bash
uv run python deploy/own-account/deploy.py staging down --region us-east-1
```

**Step 7.** Copy the two contract files from the bucket into `db/config/` in your clone.
The command requires checksum metadata on both objects and checks that the bucket holds
the bundle the pulled contracts describe. If it does not, nothing is written.

```bash
uv run python deploy/own-account/deploy.py contracts pull --region us-east-1
```

**Step 8.** Add the two files to git.

```bash
git add db/config/real-catalog-cache.json db/config/corpus-vocabulary-cache.json
```

Commit them.

```bash
git commit -m "Pin my catalog bundle"
```

Push them to your fork. The stack clones your fork, so it must hold the contract that
matches your bundle.

```bash
git push
```

**Step 9.** Upload the templates, the bootstrap script and the editor launcher to the
same bucket, along with the staging template and a `RELEASE.json`. The command also
checks the bundle already there against the contracts you committed, by size and checksum
recorded on each object, without downloading it. In a Region other than `us-east-1`, its last
step, after the uploads and the bundle check, waits until the bucket's global endpoint
answers, and prints "waiting for the bucket's global endpoint" while it does.

```bash
uv run python deploy/own-account/deploy.py publish --region us-east-1
```

**Step 10.** Create the stack from your fork at the commit you just pushed (`HEAD`).
The command refuses a working tree with uncommitted changes, including untracked files. It
waits out a rollback, and prints the first failed events if creation fails. When creation
finishes it prints the stack's outputs, including the Code Editor token.

```bash
uv run python deploy/own-account/deploy.py deploy --region us-east-1
```

Stack creation time, which includes the host restoring the catalog and building
indexes: 46 minutes 55 seconds in the proof run (the VPC 3 minutes, Aurora 7.5 minutes, the
Code Editor stack 36 minutes, of which the catalog restore took 22).

Plain `status` redacts the Code Editor token. To read the outputs again later with the
token, run this.

```bash
uv run python deploy/own-account/deploy.py status --show-token --region us-east-1
```

They are also on the stack's **Outputs** tab in the CloudFormation console:

| Output | What it is |
|---|---|
| `CodeEditorURL` | The browser editor, with its own session token in the URL |
| `MosaicURL` | The storefront and Playground |
| `ClaudeCodeModel` | The Claude Code model, through Bedrock global inference |
| `EditorInstanceType` | The Code Editor instance type the launcher found capacity for |
| `EditorAvailabilityZoneId` | The physical zone the launcher found capacity in |
| `SourceRelease` | Your fork and the commit the host checked out |
| `DatabaseEndpoint` | The Aurora writer endpoint |
| `DatabaseVersion` | The Aurora PostgreSQL version |

If creation fails, open the stack's **Events** tab and find the first failed
resource. Do not retry blindly: the order of failures matters. The host's provisioning
runs as a systemd unit, `mosaic-bootstrap.service`, that resumes at the next boot, so an
account that patches and reboots new instances on launch (a Systems Manager State Manager
association running `AWS-RunPatchBaseline`, for example) still provisions. The proof
account has such an association: before the unit existed, two deploys failed when it
rebooted the host four minutes in; with the unit, the host rebooted three minutes into
provisioning, the unit resumed at the next boot and skipped the four finished phases, and
the stack reached `CREATE_COMPLETE` in 46 minutes 55 seconds. A failure's cause travels in the `BootstrapWaitCondition` event as the
tail of `/var/log/mosaic-bootstrap.log`; on a host that still exists, `journalctl -u
mosaic-bootstrap` and the `.done` markers under `/var/lib/mosaic-bootstrap/` show which
phase was running.

## 5. Use the workshop guide

The guide is the same one participants read at an AWS event: **Build agentic hybrid
retrieval with Amazon Aurora PostgreSQL**. Follow it from its Getting started page.

The guide says to read your environment from the **Event outputs** panel of an AWS
event. In your account, the stack's **Outputs** tab holds the same names. Open
`CodeEditorURL` where the guide says to open Code Editor, and `MosaicURL` where it
says to open Mosaic. Then follow Lab 1.

Two differences to expect:

- The guide's Region hint says "your event's AWS Region (usually `us-east-1`)". Read
  it as the Region you chose in section 2.
- Lab 3's CloudWatch traces appear in that Region, so set the console to it.

## 6. Tear down

Delete everything, in this order, when you finish. Download anything you want to
keep first: the database is deleted without a final snapshot.

**Step 1.** Delete the staging environment, if section 4 step 6 did not already. The
command is safe to run again. If you never finished the build, add `--force`.

```bash
uv run python deploy/own-account/deploy.py staging down --region us-east-1
```

**Step 2.** Delete the workshop stack and the private bucket, and wait for it to finish.

```bash
uv run python deploy/own-account/deploy.py teardown --delete-bucket --region us-east-1
```

Wait for `DELETE_COMPLETE`, and resolve any failed deletions in the stack's **Events**
tab. The stack removes the database, instances, host, NAT gateway, distributions,
generated secrets and the AgentCore Runtime, Gateway and Memory resources. The
encryption keys enter a seven-day deletion window. The bucket holds your catalog
bundle, so leave out `--delete-bucket` if you want to deploy again without rebuilding it.
`--delete-bucket` refuses a bucket without the `MosaicOwnAccount=true` tag, and a name that does
not start with `mosaic-own-account-` unless you named it yourself with `--bucket`.

**Step 3, usually a few hours later.** The two runtimes reach Aurora through a network
interface that AgentCore creates in your VPC, and AWS keeps that interface for up to 8 hours
after the runtimes are deleted ([Configure Amazon Bedrock AgentCore Runtime and tools for
VPC](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/agentcore-vpc.html)); only
AWS can remove it. Until then, the two security groups it uses and the VPC around them cannot
be deleted. When that is all that blocks the delete, `teardown` deletes everything else (the
database, host, NAT gateway, distributions and runtimes), sets those resources aside, and
ends with `NOT FINISHED` and the interface's ID. What remains costs nothing. In the proof run
the first pass took 25 minutes, and AWS removed the interface about 7 hours 45 minutes after
the runtimes were deleted. Once the command it prints shows no interface, run the same
`teardown` command again. CloudFormation never retries resources a delete set aside, so this
second run deletes them itself (the Code Editor stack, then the database client security
group) and then the rest; in the proof run it took about a minute.

Some things outlive the stack and the staging environment, and you remove them yourself:

- The PostgreSQL log groups of the workshop database and of the staging database. Remove
  them, or give them a retention period that fits your policy.
- The `RDSOSMetrics` log group. Remove only this workshop's streams, because other
  databases in the account may share it.
- The AgentCore runtime log groups, `/aws/bedrock-agentcore/runtimes/<id>`, one for each
  runtime.
- The builder's log group, which `staging down` leaves in place; its events expire after 7 days. CloudFormation names it
  `<staging stack name>-BuilderLogs-<id>`; `staging down` prints the name.
- The KMS keys of both stacks (three in the workshop stack, one in the staging stack),
  which stay in their seven-day deletion window and then disappear.
- CloudWatch Transaction Search, an account-wide setting per Region that the stack turns
  on so Lab 3's agent runs appear in the CloudWatch GenAI Observability pages, with every
  span indexed. Deleting the stack puts back what it changed: the indexing percentage, the
  trace destination and the resource policy it created. The two log groups `aws/spans` and
  `/aws/application-signals/data` are removed only when they did not exist before and still
  hold no traces; once a session has run, they stay with the traces recorded while the
  setting was on, yours and any other traced application's, because deleting them would
  erase that history. An account where Transaction Search was already on is left as it
  was. The teardown command prints the setting's state and which of the two groups remain;
  confirm with `aws xray get-trace-segment-destination`.

Your fork stays until you delete it on GitHub.

## 7. Adapt it to your own data

Once the labs make sense, move the pattern to your own data and application. See
[Take this retrieval into your own agent](use-in-your-app.md) for the files to adapt,
the tool contracts and the citation checks.

## What the proof run measured

The values on this page come from one run of it in a maintainer's own account on
30 October 2026: the catalog built in us-east-1, the stack deployed and the labs run in
us-west-2. The record, with every timing and the defects the run found and fixed, is
[`docs/evidence/own-account-proof-2026-10-30.md`](evidence/own-account-proof-2026-10-30.md).
Two things it did not measure: an uninterrupted evidence step (the source host's rate limit
stopped two runs) and your account's default Embed v4 quota.
