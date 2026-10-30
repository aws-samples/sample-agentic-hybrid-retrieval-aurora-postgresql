# Workshop Studio publishing instructions

First-time cloning and pulling are covered in [the setup guide](workshop-studio-setup.md).
Copy the section below into your workshop repo's `AGENTS.md` or `CLAUDE.md`.
These steps apply to any workshop; use its own tooling, asset contracts, and target.
The command examples below use Mosaic's release tools.

## Workshop Studio publication

When asked to publish or update a build, complete the following workflow without
asking again at each upload, sync, commit, or push. Read both repositories'
instructions and required validation gates first. Report any actual blocker.

1. **Validate and publish source first.** Finish the application changes, pass
   the required checks, and commit/push or merge them to the source release
   branch. For Mosaic, use the source README's offline and Aurora release gates;
   required failed or unavailable checks block release. Use Aurora only.
2. **Update all workshop pins together.** Fetch source `origin/main`, then confirm
   the source checkout is clean and `HEAD` matches `origin/main`. Run the
   workshop's release-pin tool to update source revision, bootstrap hash, and
   infrastructure revision together. Never edit one pin in isolation.
3. **Validate the workshop.** Run its complete publishing gate. For Mosaic, this
   is in `FACILITATOR_GUIDE.md`. Resolve failures before uploading.
4. **Upload the complete assets.** Confirm the workshop ID and S3 prefix in the
   target workshop and repository. Use that workshop's scoped authoring
   credentials, never participant credentials or another workshop's credentials.
   Confirm all required Git-ignored assets are present, review a dry run, then
   sync without `--delete`: a release only adds its own folder. A dry run may add
   the new release's files; it must not update any existing object. Verify
   uploaded hashes against the release contracts. Only the latest build is kept:
   once the new build succeeds, retire the previous release folder as the
   workshop's `assets/README.md` describes.
5. **Sync static URLs.** In Workshop Studio → **Asset static URLs**, select changed
   or out-of-sync assets → **Sync static URLs** → review changes → start sync.
   Wait for **In sync**, with no pending or failed syncs. S3 upload alone does
   not refresh static URLs.
6. **Commit/push the workshop, then verify its build.** Only after static URL sync
   finishes, stage the reviewed workshop files, commit, and push to the configured
   workshop branch. Wait for the resulting build to succeed and record its
   ID/link. A successful push is not build verification.
7. **Verify deployment when requested.** Complete CloudFormation, bootstrap,
   application acceptance, and the repository's fresh-account rehearsal gates.
   Report the source SHA, workshop commit, build ID/link, and remaining blockers.

For content-only changes, skip asset upload/static URL sync only after confirming
no assets changed—including ignored files—and the relevant URLs are already
**In sync**. If a push happened too early, finish the sync and make a subsequent
commit/push; verify the later build. A build update does not authorize wider
public-catalog publication. Keep secrets out of files, logs, and responses.

### Template ownership

This repository owns the four shared CloudFormation templates (main, VPC, database, Code
Editor), the one own-account template (staging, which no event uses) and the editor launcher in
`deploy/cloudformation/`, because the own-account path publishes them too (see
[Run Mosaic in your own account](run-in-your-own-account.md)). The workshop repository keeps
copies at its existing paths and `scripts/repin.py` refreshes them from here, rewriting only
the five pinned `Default:` lines (`SourceRevision`, `InfrastructureRevision`,
`BootstrapScriptSha256`, `EditorLauncherArchiveName`, `EditorLauncherCodeSha256`), exactly
as it already copies `deploy/mosaic-bootstrap.sh`. Edit templates here, never in the
workshop repository; its validator fails when a copy differs. Push this repository first,
as step 1 says, because repin refuses an unpushed source.

### Mosaic command reference

Set `SOURCE_REPO` and `WORKSHOP_REPO` to the two checkout paths. From the workshop
checkout, repin and check:

```bash
cd "$WORKSHOP_REPO"
uv run --no-project --with PyYAML==6.0.3 python scripts/repin.py \
  --source-repo "$SOURCE_REPO"
uv run --no-project --with PyYAML==6.0.3 python scripts/repin.py --check \
  --source-repo "$SOURCE_REPO"
```

Use the confirmed asset prefix as `ASSET_ROOT`. Mosaic's prefix is
`s3://ws-assets-us-east-1/d2acf248-2981-4292-a41c-60a0a0e54ab3`; confirm it in the
workshop before use. Its complete assets are the latest release folder under
`assets/releases/<InfrastructureRevision>/` (three nested templates, the bootstrap
and `RELEASE.json`), three real-catalog parts, and two real-catalog vocabulary
files. The assets root holds no templates or bootstrap; the workshop validator
fails on one. `scripts/repin.py` writes the new release folder; never edit an
existing one. Follow `assets/README.md` for local verification, distribution
requirements and retiring the previous release once the new build succeeds.

Review the dry run before executing the upload. The sync never passes `--delete`,
so it cannot remove an object the running build still loads. It may add this
release's folder; any update of an existing object is a blocker. Retiring the
previous release is a separate, audited step that the workshop repository's
`AGENTS.md` describes:

```bash
REVISION=$(python3 -c 'import re; print(re.search(r"InfrastructureRevision\n\s+defaultValue: \"(\w+)\"", open("contentspec.yaml").read()).group(1))')
aws s3 sync ./assets "$ASSET_ROOT" --dryrun
```

```bash
aws s3 sync ./assets "$ASSET_ROOT"
python3 scripts/verify_published_bootstrap.py \
  --s3-uri "$ASSET_ROOT/releases/$REVISION/mosaic-bootstrap.sh"
python3 scripts/verify_published_catalog.py \
  --s3-uri "$ASSET_ROOT/real-catalog/" --source-repo "$SOURCE_REPO"
```

Complete `FACILITATOR_GUIDE.md` → **Event-owner preflight, step 3** for uploaded
template and vocabulary verification. Then complete the static URL sync in step
5 above before any workshop staging, commit, or push. Mosaic's workshop branch
is `mainline`; its source branch is `main`.
