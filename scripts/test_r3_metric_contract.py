"""Small synthetic contract checks; no corpus, labels, model or network."""
from copy import deepcopy
from dataclasses import replace
import math
import unittest

from rca_ml import r3_metric_contract as c
from r3_metric_contract_gate import decode_capture, matrix


VALUES = {"cpu": .1, "memory": 64*1024**2, "error": 0., "latency": .02}


def period(start=1000, *, specs=None, units=None, changes=None, states=None, service="a"):
    specs = deepcopy(specs or c.canonical_specs())
    for family, unit in (units or {}).items():
        specs[family]["unit"] = unit
    records = []
    for family in c.FAMILIES:
        state = (states or {}).get(family, "OBSERVED")
        for i in range(21):
            value = (changes or {}).get(family, VALUES[family])
            records.append(dict(service=service, family=family, timestamp=start+i*2,
                                state=state, value=value/c.UNITS[family][specs[family]["unit"]]
                                if state == "OBSERVED" else None))
    return c.normalize_period(start=start, end=start+40, step=2,
                              services=[service], specs=specs, records=records)


class MetricContract(unittest.TestCase):
    def test_four_family_schema(self):
        result = c.extract(c.fit_reference(period()), period(2000))
        self.assertEqual(len(result["columns"]), 28)
        self.assertEqual(len(set(result["columns"])), 28)
        self.assertFalse(result["ranking_computed"])
        self.assertEqual(result["saturated_observations"], 0)

    def test_all_unit_conversions_before_statistics(self):
        units = dict(cpu="millicores", memory="KiB", error="percent", latency="milliseconds")
        changes = dict(cpu=.3, memory=80*1024**2, error=.05, latency=.025)
        a = c.extract(c.fit_reference(period()), period(2000, changes=changes))
        b = c.extract(c.fit_reference(period(units=units)), period(2000, units=units, changes=changes))
        for x, y in zip(a["rows"][0]["vector"], b["rows"][0]["vector"]):
            self.assertAlmostEqual(x, y, places=10)
        self.assertEqual(a["semantic_sha256"], b["semantic_sha256"])

    def test_microseconds_and_mebibytes(self):
        self.assertEqual(period().records, period(units=dict(memory="MiB", latency="microseconds")).records)

    def test_flat_scale_old_healthy_and_zero_errors(self):
        result = c.extract(c.fit_reference(period()), period(5000, changes=dict(latency=.0205, error=.05)))
        vector = dict(zip(c.COLUMNS, result["rows"][0]["vector"]))
        self.assertAlmostEqual(vector["latency_signed_median_shift"], .5)
        self.assertAlmostEqual(vector["error_signed_median_shift"], 5.)
        self.assertEqual(vector["error_persistence"], 1.)

    def test_missing_idle_outage_are_distinct(self):
        ref = c.fit_reference(period())
        vectors = []
        for state in ("MISSING", "UNAVAILABLE", "NO_ACTIVITY"):
            result = c.extract(ref, period(2000, states=dict(error=state, latency=state)))
            vector = dict(zip(c.COLUMNS, result["rows"][0]["vector"]))
            self.assertEqual(vector["error_available"], 0)
            self.assertEqual(sum(vector["error_"+f] for f in c.FIELDS[1:4]), 1)
            vectors.append(result["rows"][0]["vector"])
        self.assertEqual(len({tuple(v) for v in vectors}), 3)

    def test_healthy_support_cannot_be_fabricated(self):
        with self.assertRaisesRegex(ValueError, "HEALTHY_SUPPORT"):
            c.fit_reference(period(states=dict(error="NO_ACTIVITY")))
        p = period()
        short = replace(p, records=tuple(row for row in p.records if row[2] < 1038))
        with self.assertRaisesRegex(ValueError, "HEALTHY_SUPPORT"):
            c.fit_reference(short)

    def test_healthy_coverage_threshold(self):
        p = period()
        # Keep 20 observed points but add six explicitly missing grid points.
        rows = p.records + tuple(("a", f, 1042+i*2, "MISSING", None)
                                 for f in c.FAMILIES for i in range(6))
        with self.assertRaisesRegex(ValueError, "HEALTHY_SUPPORT"):
            c.fit_reference(replace(p, end=1052, records=rows))

    def test_future_or_overlapping_healthy_rejected(self):
        for start in (900, 1020, 1040):
            with self.subTest(start=start), self.assertRaisesRegex(ValueError, "HEALTHY_MUST_PRECEDE"):
                c.extract(c.fit_reference(period()), period(start))

    def test_no_identity_feature(self):
        left = c.extract(c.fit_reference(period()), period(2000))["rows"][0]["vector"]
        right = c.extract(c.fit_reference(period(service="renamed")), period(2000, service="renamed"))["rows"][0]["vector"]
        self.assertEqual(left, right)
        with self.assertRaisesRegex(ValueError, "INVENTORY_MISMATCH"):
            c.extract(c.fit_reference(period()), period(2000, service="renamed"))

    def test_old_schema_rejected(self):
        ref = replace(c.fit_reference(period()), schema_sha256="old-cache56")
        with self.assertRaisesRegex(ValueError, "CONTRACT_OR_INVENTORY"):
            c.extract(ref, period(2000))

    def test_other_statistics_are_not_renamed(self):
        for family, field, value in (("latency", "statistic", "p90"),
                                     ("error", "source_kind", "counter"),
                                     ("cpu", "unit", "percent"),
                                     ("error", "population", "client_requests"),
                                     ("latency", "lookback_seconds", 60),
                                     ("latency", "aggregation", "mean_replica_quantiles")):
            specs = c.canonical_specs()
            specs[family][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                c.validate_specs(specs)

    def test_labels_and_unknown_fields_rejected(self):
        specs = c.canonical_specs()
        specs["cpu"]["root_cause"] = "a"
        with self.assertRaises(ValueError):
            c.validate_specs(specs)
        with self.assertRaisesRegex(ValueError, "POINT_FIELDS_INVALID"):
            self.normalize([dict(service="a", family="cpu", timestamp=1000,
                                 state="OBSERVED", value=.1, label=1)])

    @staticmethod
    def normalize(records):
        return c.normalize_period(start=1000, end=1040, step=2, services=["a"],
                                  specs=c.canonical_specs(), records=records)

    def test_duplicate_unaggregated_or_offgrid_points_rejected(self):
        row = dict(service="a", family="cpu", timestamp=1000, state="OBSERVED", value=.1)
        with self.assertRaisesRegex(ValueError, "DUPLICATE"):
            self.normalize([row, row])
        for stamp in (999, 1001, 1042):
            with self.subTest(stamp=stamp), self.assertRaisesRegex(ValueError, "QUERY_GRID"):
                self.normalize([row | dict(timestamp=stamp)])

    def test_nonfinite_negative_and_bad_fraction_rejected(self):
        for value in (math.nan, math.inf, -.1, 1.01, True):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.normalize([dict(service="a", family="error", timestamp=1000,
                                     state="OBSERVED", value=value)])

    def test_unobserved_requires_no_value(self):
        for family, state, value in (("error", "MISSING", 0), ("cpu", "NO_ACTIVITY", None)):
            with self.assertRaises(ValueError):
                self.normalize([dict(service="a", family=family, timestamp=1000, state=state, value=value)])

    def test_omitted_points_are_missing_not_normal(self):
        p = self.normalize([])
        self.assertEqual(len(p.records), 84)
        self.assertTrue(all(row[3:] == ("MISSING", None) for row in p.records))

    def test_finite_matrix_and_explicit_saturation(self):
        result = c.extract(c.fit_reference(period()), period(2000, changes=dict(latency=1e308)))
        self.assertEqual(result["saturated_observations"], 21)
        self.assertTrue(all(math.isfinite(x) for x in result["rows"][0]["vector"]))


class CaptureContract(unittest.TestCase):
    @staticmethod
    def raw(up=1, rate=3, value=.01):
        return {channel: [dict(metric=dict(service="a"), values=[[1000, number], [1002, number]])]
                for channel, number in (("up", up), ("request_rate", rate),
                                        ("error_ratio", value), ("latency_p95", value))}

    @staticmethod
    def decode(raw):
        return decode_capture(dict(start_unix=1000, end_unix=1002, candidate_services=["a"], metrics=[]),
                              dict(query_step_seconds=2, metrics="available"), raw, ["a"])

    def test_stale_rate_not_evidence_of_availability(self):
        p = self.decode(self.raw(up=0))
        self.assertTrue(all(r[3:] == ("UNAVAILABLE", None) for r in p.records if r[1] in {"error", "latency"}))

    def test_idle_is_not_normal_zero(self):
        p = self.decode(self.raw(rate=0, value="NaN"))
        self.assertTrue(all(r[3:] == ("NO_ACTIVITY", None) for r in p.records if r[1] in {"error", "latency"}))

    def test_missing_scrape_not_inferred_from_finite_values(self):
        raw = self.raw()
        raw["up"] = []
        p = self.decode(raw)
        self.assertTrue(all(r[3:] == ("MISSING", None) for r in p.records))

    def test_observed_zero_errors_is_available(self):
        p = self.decode(self.raw(value=0))
        self.assertTrue(all(r[3:] == ("OBSERVED", 0.) for r in p.records if r[1] == "error"))

    def test_negative_rate_or_bad_presence_rejected(self):
        for raw in (self.raw(rate=-1), self.raw(up=2)):
            with self.assertRaises(ValueError):
                self.decode(raw)

    def test_resource_outage_without_samples_is_not_missing(self):
        p = decode_capture(dict(start_unix=1000, end_unix=1002, candidate_services=["a"], metrics=[]),
                           dict(query_step_seconds=2, metrics="unavailable"), self.raw(), ["a"])
        self.assertTrue(all(r[3:] == ("UNAVAILABLE", None) for r in p.records if r[1] in {"cpu", "memory"}))

    def test_unknown_resource_source_state_is_not_outage(self):
        with self.assertRaisesRegex(ValueError, "SOURCE_STATE_NOT_DECLARED"):
            decode_capture(dict(start_unix=1000, end_unix=1002, candidate_services=["a"], metrics=[]),
                           dict(query_step_seconds=2, metrics="unknown"), self.raw(), ["a"])

    def test_duplicate_or_unknown_series_rejected(self):
        raw = self.raw()
        for rows in (raw["up"]*2, [dict(metric=dict(service="unknown"), values=[[1000, 1]])]):
            with self.assertRaises(ValueError):
                matrix(rows, ["a"], 1000, 1002, 2)


if __name__ == "__main__":
    unittest.main()
