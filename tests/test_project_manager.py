import json
import tempfile
import unittest
from pathlib import Path
import importlib.util
import sys

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "pm_candidate", ROOT / "__init__.py", submodule_search_locations=[str(ROOT)]
)
pm = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = pm
spec.loader.exec_module(pm)

class ProjectTests(unittest.TestCase):
    def test_first_run_and_versioned_edit(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d) / "project"
            root.mkdir()
            self.assertEqual(pm.initialize(str(root), "demo")["projectId"], "demo")
            self.assertEqual(json.loads((root / ".hermespm-project.json").read_text()),
                             {"schema": 1, "projectId": "demo"})
            pm.organize(str(root), "sec", "section", "Planning")
            pm.organize(str(root), "task", "unit", "First task", "sec", "seed")
            self.assertEqual(pm.list_units(str(root))["sections"][0]["units"][0]["source"], "seed")
            pm.edit(str(root), "task", 1, "draft", "draft text", "evt-2")
            self.assertEqual(pm.read(str(root), "task")["version"], 2)
            with self.assertRaises(Exception):
                pm.edit(str(root), "task", 1, "draft", "stale", "evt-3")

    def test_initialize_never_overwrites(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / ".hermespm-project.json").write_text('{"schema":1,"projectId":"prior"}')
            with self.assertRaises(Exception):
                pm.initialize(str(root), "new")
            self.assertIn("prior", (root / ".hermespm-project.json").read_text())

if __name__ == "__main__":
    unittest.main()
