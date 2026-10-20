"""A shipped product archive must start without the independent test corpus."""

from __future__ import annotations

import json
import shutil
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from zipfile import ZipFile

from server import DiagnosticApplication


ROOT = Path(__file__).resolve().parents[2]


class ProductBundleTests(unittest.TestCase):
    def test_optional_workspace_and_provider_are_explicit_clean_compositions(self):
        from importlib.util import module_from_spec, spec_from_file_location
        spec = spec_from_file_location("optional_builder", ROOT / "deploy/product/build_bundle.py")
        module = module_from_spec(spec)
        spec.loader.exec_module(module)
        # Composition does not require a local live-acceptance installation.
        # This prepared control fixture is tracked in a clean public checkout.
        profile = ROOT / "deploy/profiles/lab-system.json"
        with tempfile.TemporaryDirectory() as temporary:
            for assistant in (False, True):
                output = Path(temporary) / ("assistant.zip" if assistant else "workspace.zip")
                module.build(ROOT, profile, output, with_workspace=True, with_assistant=assistant)
                installed = Path(temporary) / ("assistant" if assistant else "workspace")
                with ZipFile(output) as archive:
                    names = archive.namelist()
                    self.assertIn("cmd/thesis_demo/workspace_store.py", names)
                    for notice in ("LICENSE", "NOTICE", "THIRD_PARTY.md", "THIRD_PARTY_NOTICES"):
                        self.assertIn(notice, names)
                    self.assertEqual("cmd/thesis_demo/assistant_worker.py" in names, assistant)
                    self.assertEqual("requirements-assistant.txt" in names, assistant)
                    self.assertFalse(any(".rca-private" in n or "evaluation" in n or "external-data" in n or "test_" in n for n in names))
                    manifest = json.loads(archive.read("bundle-manifest.json"))
                    self.assertFalse(manifest["capabilities"]["external_transmission_enabled"])
                    self.assertFalse(manifest["capabilities"]["credentials_included"])
                    archive.extractall(installed)
                environment = os.environ | {"PYTHONPATH": os.pathsep.join((str(installed / "ml"), str(installed / "cmd/thesis_demo")))}
                script = ("from pathlib import Path; from server import DiagnosticApplication; "
                    "from workspace_store import WorkspaceStore; from investigations import InvestigationService; "
                    "s=WorkspaceStore(Path('private')); service=InvestigationService(s); "
                    "app=DiagnosticApplication(Path.cwd(),workspace=s,investigations=service); "
                    "assert list(app.profiles)==['lab-system'],app.profile_errors; "
                    "assert app.runtime is None; service.close(); print('optional-cold-import-ok')")
                cold = subprocess.run([sys.executable, "-c", script], cwd=installed, env=environment,
                                      capture_output=True, text=True, timeout=30)
                self.assertEqual(cold.returncode, 0, cold.stderr)
                self.assertIn("optional-cold-import-ok", cold.stdout)

    def test_bundle_contains_only_runtime_assets_and_starts(self):
        from importlib.util import module_from_spec, spec_from_file_location

        spec = spec_from_file_location("product_builder", ROOT / "deploy/product/build_bundle.py")
        module = module_from_spec(spec)
        assert spec and spec.loader
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "source"
            for name in ("m10c-v2", "m10d-integration", "m11", "m12", "m13"):
                shutil.copytree(ROOT / "ml/models" / name, root / "ml/models" / name)
            shutil.copytree(ROOT / "ml/rca_ml", root / "ml/rca_ml", ignore=shutil.ignore_patterns("__pycache__"))
            shutil.copytree(ROOT / "cmd/thesis_demo", root / "cmd/thesis_demo",
                            ignore=shutil.ignore_patterns("__pycache__"))
            (root / "ml/pyproject.toml").write_bytes((ROOT / "ml/pyproject.toml").read_bytes())
            guide = root / "deploy/product/README.md"
            guide.parent.mkdir(parents=True)
            guide.write_bytes((ROOT / "deploy/product/README.md").read_bytes())
            (root / "deploy/product/verify_bundle.py").write_bytes(
                (ROOT / "deploy/product/verify_bundle.py").read_bytes()
            )
            (root / "deploy/product/runtime-pyproject.toml").write_bytes(
                (ROOT / "deploy/product/runtime-pyproject.toml").read_bytes()
            )
            (root / "docs").mkdir()
            shutil.copyfile(ROOT / "docs/HTTP_OBSERVATIONS.md", root / "docs/HTTP_OBSERVATIONS.md")
            for name in ("CONTEXT_PROBE.md", "DOCKER_CONTEXT.md"):
                shutil.copyfile(ROOT / "docs" / name, root / "docs" / name)
            (root / "tools").mkdir()
            for name in ("loki_context_probe.py", "docker_context_collector.py"):
                shutil.copyfile(ROOT / "tools" / name, root / "tools" / name)
            for name in ("LICENSE", "NOTICE", "THIRD_PARTY.md", "THIRD_PARTY_NOTICES"):
                (root / "deploy/product" / name).write_bytes((ROOT / "deploy/product" / name).read_bytes())
            artifact = root / "deploy/profiles/artifacts/portable"
            artifact.mkdir(parents=True)
            for name in ("healthy-baseline.json", "legacy-metric-baseline.json"):
                shutil.copyfile(ROOT / "ml/models/m14" / name, artifact / name)
            profile = json.loads((ROOT / "deploy/profiles/lab-system.json").read_text())
            profile["id"] = "portable"
            profile["artifact_dir"] = "deploy/profiles/artifacts/portable"
            profile_path = root / "deploy/profiles/portable.json"
            profile_path.write_text(json.dumps(profile))
            archive_path = Path(temporary) / "product.zip"
            module.build(root, profile_path, archive_path)
            with ZipFile(archive_path) as archive:
                self.assertIsNone(archive.testzip())
                self.assertFalse(any(name.startswith("ml/models/m14/") for name in archive.namelist()))
                self.assertFalse(any(name.startswith("ml/models/m10d-integration/") for name in archive.namelist()))
                self.assertNotIn("ml/rca_ml/m12_evaluate.py", archive.namelist())
                self.assertNotIn("ml/rca_ml/m14_runtime.py", archive.namelist())
                self.assertNotIn("cmd/thesis_demo/evaluation_ledger.py", archive.namelist())
                self.assertNotIn("cmd/thesis_demo/assistant_worker.py", archive.namelist())
                self.assertIn("cmd/thesis_demo/assistant_context.py", archive.namelist())
                self.assertIn("cmd/thesis_demo/http_observations.py", archive.namelist())
                self.assertIn("docs/HTTP_OBSERVATIONS.md", archive.namelist())
                self.assertIn("tools/docker_context_collector.py", archive.namelist())
                self.assertIn("docs/DOCKER_CONTEXT.md", archive.namelist())
                self.assertFalse(any("evaluation" in name or "external-data" in name for name in archive.namelist()))
                self.assertFalse(any(name.endswith(("m14_evaluate.py", "m13_experiment.py", "train.py"))
                                     for name in archive.namelist()))
                archive.extractall(Path(temporary) / "installed")
            verify_spec = spec_from_file_location("bundle_verifier", ROOT / "deploy/product/verify_bundle.py")
            verifier = module_from_spec(verify_spec)
            assert verify_spec and verify_spec.loader
            verify_spec.loader.exec_module(verifier)
            installed = Path(temporary) / "installed"
            self.assertEqual(verifier.verify(installed)["status"], "ok")
            one_file = installed / "README.md"
            one_file.write_bytes(one_file.read_bytes() + b"corruption")
            with self.assertRaisesRegex(ValueError, "checksum differs"):
                verifier.verify(installed)
            one_file.write_bytes((ROOT / "deploy/product/README.md").read_bytes())
            app = DiagnosticApplication(Path(temporary) / "installed")
            self.assertEqual(list(app.profiles), ["portable"])
            self.assertIsNone(app.runtime)
            # Fresh imports must not be masked by the parent's sys.modules.
            environment = os.environ | {"PYTHONPATH": os.pathsep.join((str(installed / "ml"), str(installed / "cmd/thesis_demo")))}
            cold = subprocess.run([sys.executable, "-c",
                "from pathlib import Path; from server import DiagnosticApplication; "
                "app = DiagnosticApplication(Path.cwd()); "
                "assert list(app.profiles) == ['portable'], app.profile_errors; "
                "assert app.runtime is None; print('clean-process-ok')"],
                cwd=installed, env=environment, capture_output=True, text=True, timeout=30)
            self.assertEqual(cold.returncode, 0, cold.stderr)
            self.assertIn("clean-process-ok", cold.stdout)


if __name__ == "__main__":
    unittest.main()
