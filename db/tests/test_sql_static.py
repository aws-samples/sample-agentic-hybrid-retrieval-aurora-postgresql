import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent

#: A DROP with no matching CREATE in its file: an older signature the file removes
#: on clusters that still hold it. Each entry is (file, function, argument types).
LEGACY_DROPS = {
    (
        "labs/lab1_retrieve/hybrid_search.sql",
        "mosaic_search.search_hybrid_rrf",
        ("text", "vector", "jsonb") + ("integer",) * 5 + ("real", "real"),
    ),
    (
        "labs/lab1_retrieve/solution/hybrid_search.sql",
        "mosaic_search.search_hybrid_rrf",
        ("text", "vector", "jsonb") + ("integer",) * 5 + ("real", "real"),
    ),
}

_HEADER = re.compile(
    r"(?P<kind>DROP\s+FUNCTION\s+IF\s+EXISTS|CREATE\s+OR\s+REPLACE\s+FUNCTION)"
    r"\s+(?P<name>[\w.]+)\s*\(",
    re.IGNORECASE,
)


def _argument_list(text: str, start: int) -> str:
    """The text between the parenthesis opened just before `start` and its match."""
    depth, quote = 1, None
    for index in range(start, len(text)):
        char = text[index]
        if quote:
            quote = None if char == quote else quote
        elif char in "'\"":
            quote = char
        elif char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return text[start:index]
    raise ValueError("unbalanced parentheses in a function signature")


def _split_top_level(arguments: str) -> list[str]:
    parts, depth, quote, current = [], 0, None, ""
    for char in arguments:
        if quote:
            quote = None if char == quote else quote
        elif char in "'\"":
            quote = char
        elif char in "([":
            depth += 1
        elif char in ")]":
            depth -= 1
        if char == "," and depth == 0 and not quote:
            parts.append(current)
            current = ""
        else:
            current += char
    if current.strip():
        parts.append(current)
    return parts


def _normalize(type_name: str) -> str:
    collapsed = re.sub(r"\s+", " ", type_name.strip().lower())
    return re.sub(r"\bvector\s*\(\s*\d+\s*\)", "vector", collapsed)


def argument_types(arguments: str, *, named: bool) -> tuple[str, ...]:
    """Argument types only: names and defaults do not count."""
    types = []
    for part in _split_top_level(arguments):
        part = re.split(
            r"\s+DEFAULT\s+|\s*=\s*", part, maxsplit=1, flags=re.IGNORECASE
        )[0]
        part = part.strip()
        if named:
            part = part.split(None, 1)[1]
        types.append(_normalize(part))
    return tuple(types)


def signatures(sql: str) -> tuple[list[tuple], list[tuple]]:
    """The (name, types) of every DROP FUNCTION IF EXISTS and CREATE OR REPLACE FUNCTION."""
    sql = re.sub(r"--[^\n]*", "", sql)
    drops, creates = [], []
    for match in _HEADER.finditer(sql):
        arguments = _argument_list(sql, match.end())
        is_drop = match.group("kind").upper().startswith("DROP")
        found = (
            match.group("name").lower(),
            argument_types(arguments, named=not is_drop),
        )
        (drops if is_drop else creates).append(found)
    return drops, creates


def sql_files() -> list[Path]:
    return sorted(
        [
            *(ROOT / "sql").glob("*.sql"),
            *(REPO / "labs").glob("*/*.sql"),
            *(REPO / "labs").glob("*/solution/*.sql"),
        ]
    )


def unmatched_drops(path: Path) -> list[str]:
    """Drops whose argument types equal no CREATE OR REPLACE of the same name here."""
    drops, creates = signatures(path.read_text())
    relative = path.relative_to(REPO).as_posix()
    problems = []
    for name, types in drops:
        if (name, types) in creates or (relative, name, types) in LEGACY_DROPS:
            continue
        current = [c[1] for c in creates if c[0] == name]
        problems.append(
            f"{relative}: DROP FUNCTION {name}({', '.join(types)}) matches no "
            f"CREATE OR REPLACE FUNCTION of that name (it creates {current}); fix: "
            "make the drop list exactly the created function's argument types"
        )
    return problems


class SQLStaticTests(unittest.TestCase):
    def test_install_builds_no_search_index(self):
        text = (ROOT / "sql" / "install.sql").read_text()
        self.assertNotIn("\\ir 07_indexes.sql", text)

    def test_search_representation_is_explicit(self):
        text = (ROOT / "sql" / "06_retrieval_projection.sql").read_text()
        for field in (
            "search_document",
            "trigram_text",
            "embedding_text",
            "rerank_text",
            "embedding",
        ):
            self.assertIn(field, text)

    def test_typo_and_rrf_functions_exist(self):
        channels = (ROOT / "sql" / "08_search_channels.sql").read_text()
        hybrid = (ROOT.parent / "labs/lab1_retrieve/hybrid_search.sql").read_text()
        text = channels + hybrid
        self.assertIn("search_fuzzy", text)
        self.assertIn("search_hybrid_rrf", hybrid)
        self.assertIn("strict_word_similarity", text)

    def test_every_drop_function_matches_the_function_it_replaces(self):
        files = sql_files()
        self.assertGreaterEqual(len(files), 10)
        problems = [problem for path in files for problem in unmatched_drops(path)]
        self.assertEqual(problems, [])

    def test_the_drops_are_actually_found(self):
        drops = {
            path.name: signatures(path.read_text())[0]
            for path in sql_files()
            if "DROP FUNCTION" in path.read_text()
        }
        self.assertIn("09_weighted_fusion.sql", drops)
        self.assertIn("10_evidence_search.sql", drops)
        self.assertEqual(len(drops["09_weighted_fusion.sql"][0][1]), 12)
        self.assertEqual(len(drops["10_evidence_search.sql"][0][1]), 8)

    def test_a_stale_drop_is_reported(self):
        drops, creates = signatures(
            "DROP FUNCTION IF EXISTS s.f(text, real);\n"
            "CREATE OR REPLACE FUNCTION s.f(a text, b vector(1024) DEFAULT '{}'::jsonb)"
            " RETURNS int AS $$ SELECT 1 $$ LANGUAGE sql;"
        )
        self.assertEqual(drops, [("s.f", ("text", "real"))])
        self.assertEqual(creates, [("s.f", ("text", "vector"))])
        self.assertNotIn(drops[0], creates)


if __name__ == "__main__":
    unittest.main()
