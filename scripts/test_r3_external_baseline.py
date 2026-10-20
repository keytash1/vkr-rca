"""Addressed adapter checks, not another model/telemetry test campaign."""
import unittest
from r3_external_baseline import FAMILIES, matrix, project


def records():
    units = ("cores", "bytes", "bytes_per_second", "bytes_per_second")
    return [{"timestamp": t, "service": s, "family": f, "value": float(t + i), "unit": u}
            for t in (1, 2) for s in ("one", "two")
            for i, (f, u) in enumerate(zip(FAMILIES, units))]


class AdapterChecks(unittest.TestCase):
    def test_lossless_and_opaque_columns(self):
        frame, mapping = matrix(records(), ["one", "two"])
        self.assertEqual(frame.shape, (2, 9))
        self.assertEqual(frame.c0000_cpu.tolist(), [1., 2.])
        self.assertEqual(mapping["c0001_memory"], "two")
        self.assertEqual({key.split("_")[0] for key in mapping}, {"c0000", "c0001"})

    def test_missing_not_zero(self):
        with self.assertRaisesRegex(ValueError, "incomplete"):
            matrix(records()[:-1], ["one", "two"])

    def test_duplicate_rejected(self):
        data = records()
        with self.assertRaisesRegex(ValueError, "duplicate metric"):
            matrix(data + data[:1], ["one", "two"])

    def test_bad_unit_rejected(self):
        data = records()
        data[0]["unit"] = "percent"
        with self.assertRaisesRegex(ValueError, "unit"):
            matrix(data, ["one", "two"])

    def test_projection_preserves_first_occurrence(self):
        _, mapping = matrix(records(), ["one", "two"])
        self.assertEqual(project(["c0001_cpu", "c0000_memory", "c0001_memory"], mapping),
                         [{"service": "two", "rank": 1}, {"service": "one", "rank": 2}])
        with self.assertRaisesRegex(ValueError, "unknown"):
            project(["invented"], mapping)


if __name__ == "__main__":
    unittest.main()
