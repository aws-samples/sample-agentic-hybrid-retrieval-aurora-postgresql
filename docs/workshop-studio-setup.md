# First-time workshop repo setup

The **workshop repo** holds the guide and deployment files. A separate
**source repo**, when used, holds the application code, SQL, and bootstrap script.

## Folder layout

Keep both checkouts side by side inside one parent folder. For Mosaic:

```text
Workshops/
├── build-agentic-hybrid-retrieval-with-amazon-aurora-postgresql/
└── sample-agentic-hybrid-retrieval-aurora-postgresql/
```

Use your existing `Workshops/` folder. Before running either clone command,
`cd` into that parent folder so Git creates the two folders shown above.
If they are already arranged this way, keep them there and skip cloning.

## Clone the workshop repo

1. Go to **Workshop Studio** and open your workshop's page.
2. Click **Credentials**.
3. Copy the temporary credential commands for your operating system and paste
   them into your terminal.
4. Expand **Repository Access Instructions**. Copy the **git clone** command
   and run it from your `Workshops/` parent folder.
5. Open the folder it created: `cd your-workshop-repo`.

If Git says `remote-workshopstudio` is missing, follow the
[official setup guide](https://catalog.workshops.aws/docs/en-US/create-a-workshop/authoring-a-workshop/connecting-to-your-repository#prerequisites)
to install the plugin, then retry. Credentials expire after one hour; get fresh
ones from the same **Credentials** panel. Keep their values out of shared files.

## Clone the source repo

1. Open your workshop's source repo in GitHub. For Mosaic, use
   [sample-agentic-hybrid-retrieval-aurora-postgresql](https://github.com/aws-samples/sample-agentic-hybrid-retrieval-aurora-postgresql).
2. Click **Code** → **HTTPS** → copy the clone URL.
3. In the parent folder beside the workshop checkout, run `git clone COPIED_URL`,
   replacing `COPIED_URL` with that URL.
4. Open the source folder and follow the [developer setup guide](development.md).

GitHub pushes use your GitHub access. Workshop pushes use the Workshop Studio
credentials. Use your own configured Git identity.

## Next time: pull before editing

Refresh the Workshop Studio credentials, then run this inside each repo:

```bash
git status --short --branch
```

Review local edits or an `ahead` status before continuing. Confirm you are on
the intended branch—Mosaic uses `main` for source and `mainline` for workshop.
Then run:

```bash
git pull --ff-only
```

If the pull fails, resolve it with the repo owner; do not force-push or discard
local work. Git-ignored catalog assets must be obtained separately from the
workshop owner; cloning and pulling will not download them.

## Give your coding agent the publishing instructions

Copy the **Workshop Studio publication** section from
[the publishing instructions](workshop-studio-publishing.md) into your repo's
`AGENTS.md` or `CLAUDE.md`. Tell the agent where both checkouts are, then ask:

> Publish a Workshop Studio build update using the repository instructions.

The agent should publish source changes first, update the workshop pins, sync
assets and static URLs, then push the workshop and verify the build.
