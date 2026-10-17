import copy
from concurrent.futures import ThreadPoolExecutor
import fcntl
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

    def test_extended_actions_keep_plan_separate_from_effect_and_accept_old_records(self):
        identifier=self.create()
        record=self.store.get_investigation(identifier)["record"]
        validate_record(record,snapshot()[0])  # Existing v1 record needs no rewrite.
        record["metadata"]={"owner":"Engineer", "incident":"INC-1", "category":"latency"}
        action={"id":"measure-1","title":"Review connection pool after confirming contention",
            "owner":"","due_unix":None,"status":"proposed","importance":"normal","effort":"unknown",
            "verification":"","evidence_ids":[],"purpose":"preventive","rationale":"Conditional hypothesis",
            "verification_plan":"Repeat representative load and compare timeouts", "ticket":"TASK-1","service":"alpha"}
        record["action_items"]=[action]
        self.store.save_record(identifier,record,expected_revision=0)
        self.assertEqual(self.store.get_investigation(identifier)["record"],record)
        invalid=copy.deepcopy(record)
        invalid["action_items"][0].update(status="verified",owner="Engineer",due_unix=1100)
        with self.assertRaisesRegex(StoreError,"RECORD_ACTION_VERIFICATION_REQUIRED"):
            validate_record(invalid,snapshot()[0])
        invalid["action_items"][0]["verification"]="No effect under repeat load"
        invalid["action_items"][0]["status"]="not_verified"
        validate_record(invalid,snapshot()[0])
        for replacement in ({"service":"outside"},{"purpose":"execute"},{"rationale":"x"*2001}):
            bad=copy.deepcopy(record);bad["action_items"][0].update(replacement)
            with self.assertRaises(StoreError):validate_record(bad,snapshot()[0])

    def test_review_is_bound_to_saved_content_and_not_forged_by_client(self):
        identifier=self.create()
        with self.assertRaisesRegex(StoreError,'RECORD_REVIEW_OWNER_CONCLUSION_REQUIRED'):
            self.store.review_record(identifier,expected_revision=0)
        body=self.store.get_investigation(identifier)['record'] | {
            'metadata':{'owner':'Engineer','incident':'INC-1','category':'latency'},
            'conclusion':'Mechanism unresolved; more observations are needed.'}
        body['approval']={'record_sha256':'f'*64,'reviewed_at_unix':1000}
        self.store.save_record(identifier,body,expected_revision=0)
        self.assertNotIn('approval',self.store.get_investigation(identifier)['record'])
        reviewed=self.store.review_record(identifier,expected_revision=1)
        validate_record(reviewed['record'],snapshot()[0])
        self.assertIn('approval',reviewed['record'])
        self.assertEqual(reviewed['record']['causes'],[])  # Review is not causal proof.
        same=self.store.save_record(identifier,reviewed['record'],expected_revision=2)
        self.assertEqual(same['record']['approval'],reviewed['record']['approval'])
        changed=copy.deepcopy(same['record']);changed['symptoms']='New observations recorded'
        saved=self.store.save_record(identifier,changed,expected_revision=3)
        self.assertNotIn('approval',saved['record'])
        with self.assertRaisesRegex(StoreError,'STORE_REVISION_CONFLICT'):
            self.store.review_record(identifier,expected_revision=3)

    def test_history_filters_before_limit_and_never_treats_rank_as_confirmed(self):
        old=self.create(key="old")
        record=self.store.get_investigation(old)["record"] | {"metadata":{"owner":"","incident":"","category":"latency"}}
        record["causes"]=[{"service":"alpha","statement":"Hypothesis only","status":"hypothesis","verification":"","evidence_ids":[]}]
        record["action_items"]=[{"id":"a1","title":"Investigate","owner":"Engineer","due_unix":999,
            "status":"planned","importance":"normal","effort":"unknown","verification":"","evidence_ids":[],"service":"alpha"}]
        self.store.save_record(old,record,expected_revision=0)
        self.now[0]+=1
        for number in range(35):self.create(key=f"new-{number}")
        selected=self.store.list_investigations(service="alpha",category="latency",limit=1)
        self.assertEqual([i["id"] for i in selected],[old])
        self.assertEqual(selected[0]["confirmed_services"],[])
        self.assertEqual(selected[0]["mentioned_services"],["alpha"])
        self.assertEqual(self.store.list_investigations(service="beta"),[])
        self.assertEqual([i["id"] for i in self.store.list_investigations(action_status="overdue")],[old])
        self.assertEqual(self.store.list_investigations(project="other"),[])
        self.assertEqual(len(self.store.list_investigations(after=1001,before=1001,limit=100)),35)
        for filters in ({"after":float("nan")},{"after":1002,"before":1000},{"action_status":"executed"},{"limit":101}):
            with self.assertRaises(StoreError):self.store.list_investigations(**filters)

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

    def quota_store(self):
        return WorkspaceStore(self.path,clock=lambda:self.now[0],retention_seconds=60,
                              assistant_daily_jobs=1)

    def test_daily_reservation_survives_reopen_and_deletion_but_not_window_expiry(self):
        store=self.quota_store()
        request={"mode":"D","question":"Check"}
        identifier,_=store.create_investigation("analysis-unit",request,idempotency_key="paid-once")
        self.assertEqual(store.create_investigation("analysis-unit",request,idempotency_key="paid-once"),(identifier,False))
        self.assertEqual(store.assistant_budget_status()["reserved_jobs"],1)
        with self.assertRaisesRegex(StoreError,"STORE_ASSISTANT_DAILY_LIMIT"):
            store.create_investigation("analysis-unit",request,idempotency_key="over-limit")
        # Ordinary B work does not spend or depend on the LLM allowance.
        store.create_investigation("analysis-unit",{"mode":"B"},idempotency_key="offline")
        store.delete_snapshot("analysis-unit")
        store=self.quota_store()
        self.assertEqual(store.assistant_budget_status()["remaining_jobs"],0)
        store.put_snapshot(*snapshot(),project="project-unit")
        with self.assertRaisesRegex(StoreError,"STORE_ASSISTANT_DAILY_LIMIT"):
            store.create_investigation("analysis-unit",request,idempotency_key="after-delete")
        self.now[0]+=86400
        store.put_snapshot(*snapshot(),project="project-unit")
        store.create_investigation("analysis-unit",request,idempotency_key="next-day")
        self.assertEqual(store.assistant_budget_status()["reserved_jobs"],1)

    def test_follow_up_uses_same_daily_allowance_and_unknown_is_not_refunded(self):
        store=self.quota_store()
        identifier,_=store.create_investigation("analysis-unit",{"mode":"B"},idempotency_key="first")
        store.transition(identifier,expected=["queued"],state="completed",outcome={"status":"completed"})
        request={"mode":"D","question":"More evidence"}
        self.assertEqual(store.add_turn(identifier,request,idempotency_key="second"),(2,True))
        store.transition(identifier,expected=["queued"],state="failed",
                         outcome={"status":"failed","usage":{"accounting_complete":False}})
        self.assertEqual(store.add_turn(identifier,request,idempotency_key="second"),(2,False))
        with self.assertRaisesRegex(StoreError,"STORE_ASSISTANT_DAILY_LIMIT"):
            store.add_turn(identifier,request,idempotency_key="third")
        self.assertEqual(len(store.get_investigation(identifier)["turns"]),2)
        self.assertEqual(store.assistant_budget_status()["reserved_jobs"],1)

    def test_v2_migration_backfills_prior_llm_work_not_b(self):
        self.store.create_investigation("analysis-unit",{"mode":"D"},idempotency_key="old-llm")
        self.create(key="old-b")
        # Reproduce the preceding on-disk schema, retaining actual old turns.
        with self.store._db(write=True) as db:
            db.execute("DROP TABLE assistant_reservations")
            db.execute("PRAGMA user_version=2")
        migrated=self.quota_store()
        self.assertEqual(migrated.assistant_budget_status()["reserved_jobs"],1)
        self.assertEqual(len(migrated.list_investigations()),2)
        with migrated._db() as db:
            self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0],3)

    def test_v1_migration_keeps_existing_record_and_counts_previous_llm(self):
        identifier,_=self.store.create_investigation("analysis-unit",{"mode":"D"},idempotency_key="legacy")
        previous=self.store.get_investigation(identifier)
        with self.store._db(write=True) as db:
            db.execute("DROP TABLE assistant_reservations")
            db.execute("DROP TABLE investigation_turns")
            db.execute("PRAGMA user_version=1")
        migrated=self.quota_store()
        current=migrated.get_investigation(identifier)
        for key in ("id","analysis_id","request","record","revision","state"):
            self.assertEqual(current[key],previous[key])
        self.assertEqual(len(current["turns"]),1)
        self.assertEqual(migrated.assistant_budget_status()["reserved_jobs"],1)

    def test_concurrent_store_connections_cannot_overbook_daily_allowance(self):
        stores=[self.quota_store(),self.quota_store()]
        def reserve(index):
            try:
                stores[index].create_investigation("analysis-unit",{"mode":"D"},idempotency_key=f"parallel-{index}")
                return "reserved"
            except StoreError as error:
                return str(error)
        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertCountEqual(list(pool.map(reserve,range(2))),["reserved","STORE_ASSISTANT_DAILY_LIMIT"])
        self.assertEqual(stores[0].assistant_budget_status()["reserved_jobs"],1)

    def test_daily_limit_configuration_is_bounded_integer(self):
        for limit in (True,0,-1,201,1.5):
            with self.assertRaisesRegex(StoreError,"STORE_LIMIT_INVALID"):
                WorkspaceStore(self.path,assistant_daily_jobs=limit)

    def test_schema_migration_refuses_a_running_old_owner_without_mutation(self):
        with self.store._db(write=True) as db:
            db.execute("DROP TABLE assistant_reservations")
            db.execute("PRAGMA user_version=2")
        with (self.path/"worker.lock").open("a+b") as owner:
            fcntl.flock(owner,fcntl.LOCK_EX|fcntl.LOCK_NB)
            with self.assertRaisesRegex(StoreError,"STORE_MIGRATION_WORKSPACE_RUNNING"):
                self.quota_store()
            with self.store._db() as db:
                self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0],2)
                self.assertIsNone(db.execute("SELECT name FROM sqlite_master WHERE name='assistant_reservations'").fetchone())
        self.assertEqual(self.quota_store().assistant_budget_status()["reserved_jobs"],0)


if __name__ == "__main__":
    unittest.main()
