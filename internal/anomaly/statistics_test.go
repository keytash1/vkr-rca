package anomaly

import (
	"math"
	"testing"
)

func TestMedianAndNearestRankP95(t *testing.T) {
	if got := median([]float64{4, 1, 3, 2}); got != 2.5 {
		t.Fatalf("median = %v, want 2.5", got)
	}
	if got := percentileNearestRank([]float64{1, 2, 3, 4, 100}, 0.95); got != 100 {
		t.Fatalf("p95 = %v, want 100", got)
	}
}

func TestSmoothedErrorRate(t *testing.T) {
	want := 0.5 / 51
	if got := smoothedBaselineErrorRate(0, 50); math.Abs(got-want) > 1e-12 {
		t.Fatalf("smoothed rate = %v, want %v", got, want)
	}
}

func TestErrorRateZEdgeCasesAreFinite(t *testing.T) {
	tests := []struct {
		baselineErrors   int
		baselineRequests int
		currentErrors    int
		currentRequests  int
	}{
		{0, 0, 0, 0},
		{0, 50, 0, 20},
		{0, 50, 20, 20},
		{50, 50, 20, 20},
		{-1, 50, 0, 20},
		{0, 50, 21, 20},
	}
	for _, test := range tests {
		value := errorRateZ(test.baselineErrors, test.baselineRequests, test.currentErrors, test.currentRequests)
		if value < 0 || math.IsNaN(value) || math.IsInf(value, 0) {
			t.Fatalf("errorRateZ(%+v) = %v", test, value)
		}
	}
}
