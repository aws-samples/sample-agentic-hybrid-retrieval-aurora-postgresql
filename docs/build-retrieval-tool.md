# Build a retrieval tool

Alex needs available over-ear headphones with a microphone, within his budget. Write that rule in Python, give the search tool to an agent, and prove Aurora applied it. Use this exercise after the three labs, during flex time or as a take-home extension.

A microphone flag proves that a microphone exists. It does not prove voice clarity or microphone noise suppression. Keep those questions for the evidence step.

The takeaway remains the SQL, the eval harness and the citation guard named in the README's **Participant takeaway** table, with the [Mosaic Hybrid Retrieval Skill](../skills/mosaic-hybrid-retrieval/SKILL.md) describing how an agent calls them. This exercise is optional practice, run from the command line; no Playground page is needed for it.

## 1. Create your working file

Start from the Mosaic repository in Code Editor, with its Python dependencies installed and the API running against Aurora. Replace `YOUR_MOSAIC_APP_URL` with your Mosaic app’s base address, before `/labs` or `/catalog`. The participant instructions are in the Workshop Studio guide’s optional flex section.

```bash
export MOSAIC_API_URL=YOUR_MOSAIC_APP_URL
uv run python -m examples.call_headphones --starter .local/call_headphones.py
```

The command creates a new file and refuses to overwrite an existing one. Your copy has two marked edit points. The solved reference stays in `examples/call_headphones.py`.

## 2. Implement the filter and register the tool

In `call_filters(max_price_cents)`, return a `SearchFilters` with:

- `category_key="over-ear-headphones"`;
- `in_stock_only=True`;
- the caller's `max_price_cents`;
- `attributes={"microphone": True}`.

In `registered_tools()`, return a list containing `search_call_headphones`. `create_agent()` passes this exact list to Strands. The function's typed arguments and docstring become its tool schema through `@tool`.

The HTTP call is already connected to `POST /api/search`. That route validates the request, runs the PostgreSQL candidate searches with the filters, fuses their ranks, reranks the bounded pool, and saves the result. Forward that response unchanged so its search ID remains useful.

## 3. Check two budgets

```bash
uv run python -m scripts.check_builder_tool --module .local/call_headphones.py
```

The check calls your registered tool twice with the same Clearer calls request and different budgets. It then opens each saved search through the API. A pass requires the correct filters, nonempty eligible results, and separate search records. It rejects a missing tool, a hardcoded budget, an omitted microphone rule, and products substituted after retrieval.

Open the reported Playground links to inspect both runs. A smaller budget may remove products without changing the winner; a different winner is not required for a correct filter.

If the check fails, use the reported value and suggested edit to repair your code. Empty results require inspection, not a green check.

## 4. Let the agent call it

Use Mosaic's existing AWS credentials and model environment. `create_agent()` reads the configured model ID and region; it does not create an AWS resource.

```bash
PYTHONPATH=. uv run python .local/call_headphones.py --agent \
  --query "Headphones for video calls from home" --max-price-cents 20000
```

Watch the tool call, its budget, and the saved search ID. This small example produces a shortlist. Mosaic's complete agent adds fresh evidence reads, comparison, ranking explanations and validated citations; follow the implementation map in the [adaptation guide](use-in-your-app.md).

## Try the two agent examples in Playground

**Plan my workspace** uses the existing Lab 3 question. Watch the separate keyboard and chair searches and inspect the filters attached to each.

**Check the sources** asks about the Sonora WH-C720's fit. In Reason, open **Answer and sources → Compare the sources**. Read the specification beside the sample review, see which records were cited, and identify what they do not establish. A generic positive review cannot prove microphone quality or a measured fit claim.

## Keep the working reference

To download the exercise and implementation guide, open your Mosaic app’s base address followed by `/api/builder-package`, or keep the complete Mosaic checkout. The download contains reference patterns and exercise files; run the exercise from the full checkout, which supplies the application modules and pinned dependencies.

Strands references: [custom tools](https://strandsagents.com/docs/user-guide/concepts/tools/) and [the Bedrock model provider](https://strandsagents.com/docs/user-guide/concepts/model-providers/amazon-bedrock/).

## If you get stuck

Open these in order. The first three help you make the two edits; the fourth shows the complete repair. Keep the two-budget check and the agent call whichever path you use.

### Escape hatch 1 — What belongs in retrieval?

The caller chooses the budget. Your rule adds microphone presence, available stock and the headphone category. Aurora must apply all of them before ranking. Changing the returned list in Python would leave the saved search telling a different story.

### Escape hatch 2 — Where should you edit?

Open `.local/call_headphones.py`. Implement `call_filters` between `BUILD_FILTERS_START` and `BUILD_FILTERS_END`, then `registered_tools` between `BUILD_TOOLS_START` and `BUILD_TOOLS_END`. The HTTP call and `@tool` declaration already exist.

### Escape hatch 3 — A scoped coding prompt

Ask your coding assistant: “Read the two marked edit points in `.local/call_headphones.py`. Explain why the checker rejects the starter. Implement the available-headphones-with-a-microphone rule using the caller’s budget, then register that exact search tool. Edit only my working file. Preserve the production HTTP response and run the two-budget checker.”

### Escape hatch 4 — Complete repair

Use these two function bodies in your working copy. Preserve the existing positive-integer budget check above the filter markers.

```python
def call_filters(max_price_cents: int) -> SearchFilters:
    if (
        isinstance(max_price_cents, bool)
        or not isinstance(max_price_cents, int)
        or max_price_cents <= 0
    ):
        raise ValueError("max_price_cents must be a positive integer")
    return SearchFilters(
        category_key="over-ear-headphones",
        in_stock_only=True,
        max_price_cents=max_price_cents,
        attributes={"microphone": True},
    )


def registered_tools():
    return [search_call_headphones]
```

For full recovery, copy the solved `examples/call_headphones.py` to a new working filename and pass that filename to the checker. Keep your first attempt for comparison. Complete steps 3 and 4; opening the reference alone is not a completed exercise.
