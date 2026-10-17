import copy
import hashlib
import unittest

from evaluation_ledger import LedgerError, validate_ledger


def case(number, role="development"):
    # Artificial unit-test records, NOT collected experimental cases.
    return {"case_id": f"unit-{number}", "group_id": f"unit-group-{number}",
        "system_id": "unit-system-" + str(number % 2), "role": role,
        "input_sha256": hashlib.sha256(f"unit-input-{number}".encode()).hexdigest(),
        "gold_sha256": hashlib.sha256(f"unit-gold-{number}".encode()).hexdigest(),
        "origin": "UNIT_TEST_ONLY", "transmission": "local_only"}


class LedgerTests(unittest.TestCase):
    def test_draft_and_minimum_dataset_gate(self):
        self.assertFalse(validate_ledger([])["acceptance_ready"])
        with self.assertRaisesRegex(LedgerError, "LEDGER_NOT_ACCEPTANCE_READY"):
            validate_ledger([], require_acceptance_ready=True)
        records = [case(i, "development" if i < 30 else "locked" if i < 60 else "attack") for i in range(80)]
        self.assertTrue(validate_ledger(records, require_acceptance_ready=True)["acceptance_ready"])

    def test_same_group_or_snapshot_cannot_cross_into_locked(self):
        first, second = case(0), case(2, "locked")
        for key in ("group_id", "input_sha256"):
            duplicate = copy.deepcopy(second); duplicate[key] = first[key]
            with self.subTest(key=key), self.assertRaisesRegex(LedgerError, "LEDGER_LOCKED_CONTAMINATION"):
                validate_ledger([first, duplicate])

    def test_regression_cannot_become_new_acceptance_and_provenance_is_required(self):
        record = case(1, "locked")
        with self.assertRaisesRegex(LedgerError, "LEDGER_REGRESSION_RELABELED"):
            validate_ledger([record], regression_hashes=[record["input_sha256"]])
        for change in ({"origin": ""}, {"gold_sha256": None}, {"transmission": "corporate_unknown"}):
            with self.assertRaises(LedgerError):
                validate_ledger([record | change])


if __name__ == "__main__":
    unittest.main()
