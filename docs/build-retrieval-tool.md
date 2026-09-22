# Build a filtered retrieval tool

Alex is comparing headphone brands. Search the same need once for **Bose** and once for **Sony**. Do not use stock or microphone flags that the imported catalog does not establish.

### 1. Create a working copy

```bash
export MOSAIC_API_URL=http://127.0.0.1:8000
uv run python -m examples.call_headphones --starter .local/call_headphones.py
```

The command refuses to overwrite an existing file. Edit your copy; retain the solved reference.

### 2. Make two edits

- In `call_filters(brand)`, require `domain="consumer_electronics"`, `category_key="headphones"`, and the caller's `brand`.
- In `registered_tools()`, register `search_call_headphones`.

The supplied `@tool` and HTTP call already connect to the production search. Return its response unchanged so the saved search still explains the products you show.

### 3. Prove both calls

```bash
uv run python -m scripts.check_builder_tool --module .local/call_headphones.py
```

The checker invokes your registered tool for Bose and Sony, then reopens each saved response. Both must have nonempty results, the requested brand and headphone category, and separate search IDs. A missing filter or hardcoded brand fails.

Open a reported Playground link. Explain why the filter belongs in retrieval rather than in a Python loop that removes products afterwards.

### 4. Let the agent call your tool

```bash
PYTHONPATH=. uv run python .local/call_headphones.py --agent \
  --query "Headphones for video calls from home" --brand Bose
```

This returns a shortlist. A brand match does not establish call quality; that still needs product evidence. Download `/api/builder-package` from your Mosaic hostname to keep the example and adaptation guide.

<details>
<summary>Hint 1 — What belongs in retrieval?</summary>

The caller selects a brand. Your rule adds the electronics domain and headphone category. Aurora applies those constraints before choosing the final results.
</details>

<details>
<summary>Hint 2 — Where should you edit?</summary>

In `.local/call_headphones.py`, edit `BUILD_FILTERS_START` through `BUILD_FILTERS_END`, then `BUILD_TOOLS_START` through `BUILD_TOOLS_END`.
</details>

<details>
<summary>Hint 3 — A scoped coding prompt</summary>

“Explain why my starter fails the two-brand checker. Edit only the marked blocks in `.local/call_headphones.py`: forward the caller's brand with the electronics/headphones filters, then register the supplied tool. Preserve the HTTP response. Run the checker and explain both results.”
</details>

<details>
<summary>Hint 4 — Complete repair</summary>

Replace the filter block:

```python
    return SearchFilters(
        domain="consumer_electronics",
        category_key="headphones",
        brand=brand.strip(),
    )
```

Replace the tool-registration block:

```python
    return [search_call_headphones]
```

Preserve both function declarations and all markers, then complete steps 3 and 4.
</details>
