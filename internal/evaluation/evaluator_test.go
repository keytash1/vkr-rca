package evaluation

import (
	"testing"

	"vkr-rca/internal/diagnosis"
)

func TestEvaluateRanks(t *testing.T) {
	ranking := diagnosis.Ranking{
		{Rank: 1, Service: "payment"},
		{Rank: 2, Service: "orders"},
		{Rank: 3, Service: "gateway"},
		{Rank: 4, Service: "catalog"},
	}
	tests := []struct {
		truth string
		rank  int
		ac1   int
		ac3   int
		rr    float64
	}{
		{truth: "payment", rank: 1, ac1: 1, ac3: 1, rr: 1},
		{truth: "orders", rank: 2, ac1: 0, ac3: 1, rr: .5},
		{truth: "catalog", rank: 4, ac1: 0, ac3: 0, rr: .25},
		{truth: "missing", rank: 0, ac1: 0, ac3: 0, rr: 0},
	}
	for _, test := range tests {
		got := Evaluate(ranking, test.truth)
		if got.Rank != test.rank || got.ACAt1 != test.ac1 || got.ACAt3 != test.ac3 || got.ReciprocalRank != test.rr {
			t.Errorf("Evaluate(%q) = %+v", test.truth, got)
		}
	}
}
