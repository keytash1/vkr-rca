"""Evaluation accounting does not turn unexposed cases into effect evidence."""

import unittest

from summarize_assistant_comparison import paired_target_accounting


class PairedAccountingTests(unittest.TestCase):
    def setUp(self):
        self.groups = {"g1":{"C":0.5,"D":1.0,"E":1.0},
                       "g2":{"C":0.0,"D":0.5,"E":0.5}}

    def test_interrupted_series_has_no_interval(self):
        result = paired_target_accounting(self.groups,{"C","D","E"},
                                         all_assignments_attempted=False)
        self.assertEqual(result["status"],"NOT_ESTIMATED_INCOMPLETE_ASSIGNMENT")
        self.assertIsNone(result["estimates"])

    def test_single_cluster_is_not_precision(self):
        result = paired_target_accounting({"g1":self.groups["g1"]},{"C","D","E"},
                                         all_assignments_attempted=True)
        self.assertEqual(result["status"],"NOT_ESTIMATED_INSUFFICIENT_CLUSTERS")
        self.assertIsNone(result["estimates"])

    def test_complete_series_is_reproducible_and_explicitly_not_usefulness(self):
        kwargs = {"all_assignments_attempted":True}
        result = paired_target_accounting(self.groups,{"C","D","E"},**kwargs)
        self.assertEqual(result,paired_target_accounting(self.groups,{"C","D","E"},**kwargs))
        self.assertEqual(result["status"],"OBJECTIVE_TARGET_ACCOUNTING_ONLY_NOT_USEFULNESS")
        self.assertEqual(result["estimates"]["D-C"]["mean_difference"],0.5)
        self.assertEqual(result["estimates"]["D-E"]["mean_difference"],0.0)


if __name__ == "__main__":
    unittest.main()
