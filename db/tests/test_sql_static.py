import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class SQLStaticTests(unittest.TestCase):
    def test_install_excludes_concurrent_indexes(self):
        text = (ROOT / "sql" / "install.sql").read_text()
        self.assertNotIn("15_indexes_concurrent.sql", text)

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
        self.assertIn("search_trigram", text)
        self.assertIn("search_hybrid_rrf", hybrid)
        self.assertIn("strict_word_similarity", text)


if __name__ == "__main__":
    unittest.main()
