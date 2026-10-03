import importlib.util
import json
import sys
import unittest
from pathlib import Path

from jsonschema.validators import validator_for

ROOT = Path(__file__).resolve().parents[1]


class ContractTests(unittest.TestCase):
    def test_json_schemas_are_valid(self):
        paths = list((ROOT / "models" / "json-schema").glob("*.json"))
        self.assertGreaterEqual(len(paths), 8)
        for path in paths:
            schema = json.loads(path.read_text())
            validator_for(schema).check_schema(schema)

    def test_search_request_defaults(self):
        path = ROOT / "models" / "python" / "mosaic_models.py"
        spec = importlib.util.spec_from_file_location("mosaic_models_test", path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        request = module.SearchRequest(query="test query")
        self.assertEqual(request.profile.semantic_limit, 150)
        self.assertEqual(request.profile.iterative_scan, "relaxed_order")


if __name__ == "__main__":
    unittest.main()
