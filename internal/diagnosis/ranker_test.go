package diagnosis

import "testing"

func TestFourRankersRemainDistinctAndDeterministic(t *testing.T) {
	features := FeatureSnapshot{
		FeatureSchemaVersion: FeatureSchemaVersion,
		State:                StateReady, PrimarySignal: SignalLatency,
		ObservedAnomalies: []string{"gateway", "orders", "payment"},
		Services: []FeatureVector{
			{Service: "gateway", Ready: true, Candidate: true, LatencyZ: 60, LatencyStrength: .99, M5Severity: 18, TopologyF1: .5, LocalEvidence: .1},
			{Service: "orders", Ready: true, Candidate: true, LatencyZ: 50, LatencyStrength: .98, M5Severity: 15, TopologyF1: .8, LocalEvidence: .2},
			{Service: "payment", Ready: true, Candidate: true, LatencyZ: 40, LatencyStrength: .97, M5Severity: 12, TopologyF1: 1, LocalEvidence: .9},
		},
	}
	rca := BuildRCA(features, DefaultRankers())
	wants := map[string]string{
		"max_severity":         "gateway",
		"topology_consistency": "payment",
		"local_evidence":       "payment",
		"hybrid_v1":            "payment",
	}
	for method, want := range wants {
		ranking := rca.Rankings[method]
		if len(ranking) != 3 || ranking[0].Service != want {
			t.Errorf("%s ranking = %+v, want top %s", method, ranking, want)
		}
		for index, candidate := range ranking {
			if candidate.Rank != index+1 {
				t.Errorf("%s rank[%d] = %d", method, index, candidate.Rank)
			}
		}
	}
	if got := rca.Rankings["hybrid_v1"][0].Score; got != .9 {
		t.Fatalf("hybrid score = %v, want 0.9", got)
	}
}

func TestRankerTiesUseLexicalServiceName(t *testing.T) {
	features := FeatureSnapshot{
		State: StateReady, PrimarySignal: SignalError,
		Services: []FeatureVector{
			{Service: "zeta", Ready: true, Candidate: true, ErrorStrength: .8, M5Severity: 2, TopologyF1: 1, LocalEvidence: .8},
			{Service: "alpha", Ready: true, Candidate: true, ErrorStrength: .8, M5Severity: 2, TopologyF1: 1, LocalEvidence: .8},
		},
	}
	for _, ranker := range DefaultRankers() {
		ranking := ranker.Rank(features)
		if ranking[0].Service != "alpha" {
			t.Errorf("%s tie ranking = %+v", ranker.Name(), ranking)
		}
	}
}

func TestHybridTopOneForSixControlledPatterns(t *testing.T) {
	tests := []struct {
		name     string
		signal   PrimarySignal
		features []FeatureVector
		want     string
	}{
		{
			name: "payment latency", signal: SignalLatency, want: "payment",
			features: []FeatureVector{
				candidate("gateway", .5, .02, 18), candidate("orders", .8, .03, 17), candidate("payment", 1, .95, 16),
			},
		},
		{
			name: "orders latency", signal: SignalLatency, want: "orders",
			features: []FeatureVector{candidate("gateway", 2.0/3.0, .02, 18), candidate("orders", 1, .95, 17)},
		},
		{name: "gateway latency", signal: SignalLatency, want: "gateway", features: []FeatureVector{candidate("gateway", 1, .95, 18)}},
		{
			name: "payment error", signal: SignalError, want: "payment",
			features: []FeatureVector{candidate("gateway", .5, .9, 3), candidate("orders", .8, .9, 3), candidate("payment", 1, .9, 3)},
		},
		{
			name: "orders error", signal: SignalError, want: "orders",
			features: []FeatureVector{candidate("gateway", 2.0/3.0, .9, 3), candidate("orders", 1, .9, 3)},
		},
		{name: "gateway error", signal: SignalError, want: "gateway", features: []FeatureVector{candidate("gateway", 1, .9, 3)}},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			snapshot := FeatureSnapshot{State: StateReady, PrimarySignal: test.signal, Services: test.features}
			ranking := DefaultRankers()[3].Rank(snapshot)
			if len(ranking) == 0 || ranking[0].Service != test.want {
				t.Fatalf("hybrid ranking = %+v, want %s", ranking, test.want)
			}
		})
	}
}

func candidate(service string, topology, local, severity float64) FeatureVector {
	return FeatureVector{
		Service: service, Ready: true, Candidate: true,
		TopologyF1: topology, LocalEvidence: local, M5Severity: severity,
		LatencyStrength: local, ErrorStrength: local,
	}
}
