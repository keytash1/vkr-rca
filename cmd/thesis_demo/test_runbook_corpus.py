import json
from pathlib import Path
import tempfile
import unittest

from runbook_corpus import RunbookCorpus
from assistant_tools import ToolError

ROOT = Path(__file__).resolve().parents[2]


class RunbookTests(unittest.TestCase):
    def test_own_guidance_is_scoped_versioned_and_not_a_fault_answer(self):
        corpus = RunbookCorpus(ROOT / "deploy/runbooks/basic-investigation.json")
        self.assertEqual(len(corpus.for_project("petclinic")), 7)
        self.assertEqual(corpus.for_project("other-project"), [])
        self.assertEqual(len(corpus.sha256), 64)
        copy = corpus.for_project("petclinic")
        copy.clear()
        self.assertEqual(len(corpus.for_project("petclinic")), 7)

    def test_no_implicit_external_approval_or_unknown_fields(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "corpus.json"
            original = json.loads(
                (ROOT / "deploy/runbooks/basic-investigation.json").read_text()
            )
            for changed in (
                original | {"external_transmission_approved": False},
                original | {"path": "/secret"},
                original | {"projects": ["*"]},
            ):
                path.write_text(json.dumps(changed))
                with self.assertRaises(ToolError):
                    RunbookCorpus(path)
            link = Path(directory) / "link.json"
            link.symlink_to(path)
            with self.assertRaises(ToolError):
                RunbookCorpus(link)


if __name__ == "__main__":
    unittest.main()
