"""Alias text may reach the close-spelling channel, never lexeme containment.

Lab 1 teaches that `pg_trgm` is the only arm that can recover a misspelling. That
lesson is only true if the misspellings a product carries in `mosaic.product`'s
`aliases` stay out of the FTS tsvector. `mosaic_search.product_document` generates
`search_document` from `feature_text`, so putting aliases in `feature_text` puts a
product's own typos into lexeme containment and lets `search_fts` recover any typo
the Lab 1 anchor could use.

That is not hypothetical. It shipped. Measured on Aurora at the time: the lexeme
`hedphon`, which exists only because an alias supplied it, reached exactly one row
in 500,000, making that product uniquely findable by FTS for its own
misspellings. Lab 1's broken state lost nothing and the bootstrap's acceptance
check failed on every deployment.

These assertions are static on purpose. The live equivalents need a cluster, and
one of them needs Bedrock, so they can only run in release CI; this file runs in
every offline run on every machine, which is where a regression should be caught.
Falsifier: put `array_to_string(p.aliases, ' ')` back into the `feature_text`
expression and `test_feature_text_excludes_aliases` goes red with no cluster and
no model access.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROJECTION = ROOT / "db" / "sql" / "06_retrieval_projection.sql"
MISSIONS = ROOT / "data" / "evals" / "mosaic_labs_missions.json"

ALIAS_EXPRESSION = "array_to_string(p.aliases, ' ')"


def _projection_sql() -> str:
    return PROJECTION.read_text(encoding="utf-8")


def _strip_sql_comments(sql: str) -> str:
    """Drop `--` line comments, leaving quoted literals alone.

    Necessary rather than cosmetic: the comment explaining why aliases are absent
    from `feature_text` contains commas, and counting SELECT-list positions
    through it silently shifts every column index after it.
    """
    out: list[str] = []
    in_string = False
    index = 0
    while index < len(sql):
        char = sql[index]
        if in_string:
            out.append(char)
            if char == "'":
                in_string = False
            index += 1
            continue
        if char == "'":
            in_string = True
            out.append(char)
            index += 1
            continue
        if sql.startswith("--", index):
            newline = sql.find("\n", index)
            index = len(sql) if newline == -1 else newline
            continue
        out.append(char)
        index += 1
    return "".join(out)


def _select_expression(index: int) -> str:
    """Return the Nth SELECT-list expression of refresh_product_documents.

    The projection's INSERT names its columns and the SELECT supplies them
    positionally, so the only way to know which expression feeds `feature_text`
    is to count. Splitting on the column list keeps that coupling explicit
    rather than matching a substring that appears in several expressions.
    """
    sql = _strip_sql_comments(_projection_sql())
    body = sql.split("    SELECT\n", 1)[1].split("    FROM mosaic.product p", 1)[0]
    depth = 0
    current: list[str] = []
    expressions: list[str] = []
    for char in body:
        if char in "([":
            depth += 1
        elif char in ")]":
            depth -= 1
        if char == "," and depth == 0:
            expressions.append("".join(current))
            current = []
            continue
        current.append(char)
    if "".join(current).strip():
        expressions.append("".join(current))
    return expressions[index]


def _column_index(name: str) -> int:
    sql = _strip_sql_comments(_projection_sql())
    column_block = sql.split("INSERT INTO mosaic_search.product_document (", 1)[1]
    column_block = column_block.split(")\n", 1)[0]
    columns = [
        item.strip() for item in re.split(r"[,\n]", column_block) if item.strip()
    ]
    return columns.index(name)


def test_feature_text_excludes_aliases():
    """The tsvector must not learn a product's own misspellings."""
    feature_text = _select_expression(_column_index("feature_text"))
    assert "p.short_description" in feature_text, (
        "feature_text no longer looks like the expression this test guards; "
        "re-derive the column index before trusting the assertion below"
    )
    assert ALIAS_EXPRESSION not in feature_text, (
        "aliases are back in feature_text, so search_document indexes each "
        "product's own misspellings and search_fts can recover the Lab 1 target "
        "without pg_trgm"
    )


def test_trigram_text_still_includes_aliases():
    """The close-spelling channel is the arm that is *supposed* to use them."""
    trigram_text = _select_expression(_column_index("trigram_text"))
    assert ALIAS_EXPRESSION in trigram_text, (
        "trigram_text lost aliases, so the only arm that can recover the Lab 1 "
        "anchor no longer has the text it matches against"
    )


def test_embedding_text_never_included_aliases():
    """Why the fix needed no re-embedding, asserted so it stays true.

    `refresh_product_documents` nulls `embedding` whenever `embedding_text`
    changes. If aliases were ever added here, applying this contract would
    silently discard 500,000 cached embeddings.
    """
    embedding_text = _select_expression(_column_index("embedding_text"))
    assert "'Product: '" in embedding_text, (
        "embedding_text no longer looks like the expression this test guards"
    )
    assert ALIAS_EXPRESSION not in embedding_text, (
        "aliases were added to embedding_text; refresh_product_documents will "
        "null every embedding it touches and the catalog needs re-embedding"
    )


def test_search_document_is_generated_from_feature_text():
    """The assertions above only matter because of this dependency."""
    sql = _projection_sql()
    generated = sql.split("search_document", 1)[1].split("STORED", 1)[0]
    assert "GENERATED ALWAYS AS" in generated
    assert "feature_text" in generated, (
        "search_document no longer derives from feature_text, so excluding "
        "aliases there no longer keeps them out of the tsvector"
    )


def test_lab1_anchor_has_no_correctly_spelled_word():
    """Every token must miss, or FTS recovers the target on the one that hits.

    Both retired anchors failed a version of this. The first left `canceling`
    spelled correctly, which stems to the same lexeme as `cancelling`. The second
    spelled the category word `WHC720` closely enough to be an identity.
    """
    import json

    missions = json.loads(MISSIONS.read_text(encoding="utf-8"))
    mission = next(m for m in missions["missions"] if m["id"] == "typo-recovery")
    tokens = mission["query"].split()
    assert len(tokens) >= 3, "a one-word anchor cannot demonstrate a lexical miss"
    catalog_words = {
        "noise",
        "cancelling",
        "canceling",
        "headphones",
        "headphone",
        "wireless",
        "sonora",
        "battery",
        "life",
        "lightweight",
        "clear",
        "calls",
    }
    for token in tokens:
        assert token.lower() not in catalog_words, (
            f"{token!r} is spelled the way the catalog spells it, so FTS can "
            "recover the target on that token alone and the broken state stops "
            "being broken"
        )
