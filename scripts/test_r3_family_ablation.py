import unittest
from r3_family_ablation import COLS, KEEP, project
from rca_ml.m10c_schema import METRIC_FAMILIES


class ProjectionTests(unittest.TestCase):
    def vector(self):
        row={k:0.0 for k in COLS}
        for family,value in (('cpu',2),('memory',4),('latency',100)):
            row[f'metric_{family}_has']=1
            row[f'metric_{family}_max_shift']=value
            row[f'metric_{family}_persistence']=.5
            row[f'metric_{family}_max_shift_percentile']=.8
        return row

    def test_restricted_aggregates_cannot_leak_excluded_family(self):
        original=self.vector(); result=project(original,True)
        self.assertEqual(result['metric_latency_has'],0)
        self.assertEqual(result['metric_latency_max_shift_percentile'],0)
        self.assertEqual(result['metric_max_shift_score'],4)
        self.assertEqual(result['metric_top2_score'],3)
        self.assertEqual(result['metric_available_family_ratio'],2/len(METRIC_FAMILIES))
        self.assertEqual(original['metric_latency_max_shift'],100)

    def test_expansion_and_extra_fields(self):
        row=self.vector(); row.update(root='cpu',workload_residual_peak=9999,trace_error_strength=9999)
        result=project(row,False)
        self.assertEqual(set(result),set(COLS))
        self.assertEqual(result['metric_max_shift_score'],100)
        row['root']='other'
        self.assertEqual(result,project(row,False))

    def test_nonfinite_rejected(self):
        row=self.vector(); row['metric_cpu_max_shift']=float('nan')
        with self.assertRaises(ValueError): project(row,True)


if __name__=='__main__': unittest.main()
