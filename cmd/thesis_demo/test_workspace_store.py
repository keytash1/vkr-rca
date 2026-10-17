import copy
import os
from pathlib import Path
import tempfile
import unittest

from workspace_store import WorkspaceStore, StoreError, validate_record
from test_assistant_runner import catalog


def snapshot():
    c = catalog() | {"analysis_id": "analysis-unit", "input_sha256": "a" * 64}
    r = {
        "result_id": c["analysis_id"],
        "input_sha256": c["input_sha256"],
        "candidates": [
            {"service": "alpha", "rank": 1, "model_score": 0.3},
            {"service": "beta", "rank": 2, "model_score": 0.1},
        ],
    }
    return c, r


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "workspace"
        self.now = [1000.0]
        self.store = WorkspaceStore(
            self.path, clock=lambda: self.now[0], retention_seconds=60
        )
        c, r = snapshot()
        self.store.put_snapshot(c, r, project="project-unit")

    def tearDown(self):
        self.temp.cleanup()

    def create(self, **kwargs):
        return self.store.create_investigation(
            "analysis-unit",
            {"mode": "B", "question": "Check"},
            idempotency_key=kwargs.get("key", "key-unit"),
        )[0]

    def test_persists_equal_immutable_snapshot_and_project_scope_across_reopen(self):
        before = self.store.get_snapshot("analysis-unit")
        other = WorkspaceStore(
            self.path, clock=lambda: self.now[0], retention_seconds=60
        )
        self.assertEqual(before, other.get_snapshot("analysis-unit"))
        self.assertIsNone(other.get_snapshot("analysis-unit", project="other-project"))
        c, r = snapshot()
        c["requests_per_second"] += 1
        with self.assertRaisesRegex(StoreError, "STORE_IMMUTABLE_SNAPSHOT"):
            self.store.put_snapshot(c, r, project="project-unit")
        c, r = snapshot()
        r["result_id"] = "different"
        with self.assertRaisesRegex(StoreError, "STORE_SNAPSHOT_MISMATCH"):
            self.store.put_snapshot(c, r, project="project-unit")

    def test_idempotency_same_request_is_read_back_not_new_work_conflict_rejected(self):
        identifier = self.create()
        repeated, fresh = self.store.create_investigation(
            "analysis-unit",
            {"mode": "B", "question": "Check"},
            idempotency_key="key-unit",
        )
        self.assertEqual((repeated, fresh), (identifier, False))
        with self.assertRaisesRegex(StoreError, "STORE_IDEMPOTENCY_CONFLICT"):
            self.store.create_investigation(
                "analysis-unit", {"mode": "D"}, idempotency_key="key-unit"
            )
        with self.assertRaisesRegex(StoreError, "STORE_SNAPSHOT_NOT_FOUND"):
            self.store.create_investigation(
                "other-analysis", {}, idempotency_key="key-unit"
            )

    def test_restart_marks_only_unfinished_jobs_and_never_reissues_model_calls(self):
        identifier = self.create()
        completed = self.create(key="other-key")
        self.assertTrue(
            self.store.transition(identifier, expected=["queued"], state="running")
        )
        self.store.transition(
            completed,
            expected=["queued"],
            state="completed",
            outcome={"status": "completed"},
        )
        self.assertEqual(self.store.recover_interrupted(), 1)
        read = self.store.get_investigation(identifier)
        self.assertEqual(read["state"], "interrupted")
        self.assertEqual(read["outcome"]["remote_generation_stopped"], "UNKNOWN")
        self.assertEqual(self.store.get_investigation(completed)["state"], "completed")
        self.assertFalse(
            self.store.transition(identifier, expected=["running"], state="completed")
        )

    def test_follow_up_preserves_record_and_previous_answers_and_is_idempotent(self):
        identifier = self.create()
        record = self.store.get_investigation(identifier)["record"] | {
            "title": "Keep this title"
        }
        self.store.save_record(identifier, record, expected_revision=0)
        self.store.transition(
            identifier,
            expected=["queued"],
            state="completed",
            outcome={"status": "completed", "summary": "first answer"},
        )
        request = {"mode": "D", "question": "Follow-up"}
        self.assertEqual(
            self.store.add_turn(identifier, request, idempotency_key="turn-2"),
            (2, True),
        )
        self.assertEqual(
            self.store.add_turn(identifier, request, idempotency_key="turn-2"),
            (2, False),
        )
        with self.assertRaisesRegex(StoreError, "STORE_TURN_IN_PROGRESS"):
            self.store.add_turn(identifier, request, idempotency_key="turn-3")
        current = self.store.get_investigation(identifier)
        self.assertEqual(current["record"], record)
        self.assertEqual(current["revision"], 1)
        self.assertEqual(current["request"], request)
        self.assertEqual(current["turns"][0]["outcome"]["summary"], "first answer")
        self.assertIsNone(current["outcome"])

    def test_ttl_and_deletion_remove_derived_records_without_deleting_baselines(self):
        identifier = self.create()
        self.now[0] = 1061
        self.assertIsNone(self.store.get_snapshot("analysis-unit"))
        self.assertIsNone(self.store.get_investigation(identifier))
        self.assertTrue(self.store.delete_snapshot("analysis-unit"))
        with self.store._db() as db:
            self.assertEqual(
                db.execute("SELECT COUNT(*) FROM investigations").fetchone()[0], 0
            )
            self.assertEqual(list(db.execute("PRAGMA foreign_key_check")), [])

    def test_quota_refuses_without_evicting_user_work(self):
        limited = WorkspaceStore(
            self.path, max_snapshots=1, clock=lambda: self.now[0], retention_seconds=60
        )
        c, r = snapshot()
        c["analysis_id"] = r["result_id"] = "second-analysis"
        with self.assertRaisesRegex(StoreError, "STORE_CAPACITY"):
            limited.put_snapshot(c, r, project="project-unit")
        self.assertIsNotNone(limited.get_snapshot("analysis-unit"))

    def test_revision_prevents_lost_update_and_keeps_multiple_hypotheses_separate(self):
        identifier = self.create()
        record = self.store.get_investigation(identifier)["record"]
        record["title"] = "Investigation"
        record["causes"] = [
            {
                "service": "alpha",
                "statement": "Possible load change",
                "status": "hypothesis",
                "verification": "",
                "evidence_ids": ["obs-a"],
            }
        ]
        saved = self.store.save_record(identifier, record, expected_revision=0)
        self.assertEqual(saved["revision"], 1)
        with self.assertRaisesRegex(StoreError, "STORE_REVISION_CONFLICT"):
            self.store.save_record(identifier, record, expected_revision=0)
        bad = copy.deepcopy(record)
        bad["causes"][0]["status"] = "confirmed"
        with self.assertRaises(StoreError):
            self.store.save_record(identifier, bad, expected_revision=1)
        bad = copy.deepcopy(record)
        bad["causes"][0]["evidence_ids"] = ["other-analysis-fact"]
        with self.assertRaisesRegex(StoreError, "RECORD_EVIDENCE_OUTSIDE_SCOPE"):
            self.store.save_record(identifier, bad, expected_revision=1)

    def test_action_cannot_be_verified_without_result_or_planned_without_owner_due(
        self,
    ):
        identifier = self.create()
        record = self.store.get_investigation(identifier)["record"]
        action = {
            "id": "action-unit",
            "title": "Check capacity",
            "owner": "",
            "due_unix": None,
            "status": "proposed",
            "importance": "high",
            "effort": "small",
            "verification": "",
            "evidence_ids": ["obs-a"],
        }
        record["action_items"] = [action]
        validate_record(record, snapshot()[0])
        for updates in (
            {"status": "planned"},
            {"status": "verified", "owner": "Engineer", "due_unix": 1500},
        ):
            bad = copy.deepcopy(record)
            bad["action_items"][0].update(updates)
            with self.assertRaises(StoreError):
                validate_record(bad, snapshot()[0])
        action.update(
            status="verified",
            owner="Engineer",
            due_unix=1500,
            verification="Compared healthy workload, no improvement; result recorded.",
        )
        validate_record(record, snapshot()[0])

    def test_private_permissions_symlink_and_future_schema_are_not_silently_accepted(
        self,
    ):
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o700)
        self.assertEqual(self.store.path.stat().st_mode & 0o777, 0o600)
        link = Path(self.temp.name) / "link"
        link.symlink_to(self.path, target_is_directory=True)
        with self.assertRaisesRegex(StoreError, "STORE_DIRECTORY_UNSAFE"):
            WorkspaceStore(link)
        os.chmod(self.store.path, 0o644)
        with self.assertRaisesRegex(StoreError, "STORE_DATABASE_UNSAFE"):
            WorkspaceStore(self.path)
        os.chmod(self.store.path, 0o600)
        with self.store._db(write=True) as db:
            db.execute("PRAGMA user_version=99")
        with self.assertRaisesRegex(StoreError, "STORE_SCHEMA_UNSUPPORTED"):
            WorkspaceStore(self.path)


if __name__ == "__main__":
    unittest.main()
