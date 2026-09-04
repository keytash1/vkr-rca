package diagnosis

import "sort"

type Ranker interface {
	Name() string
	Rank(FeatureSnapshot) Ranking
}

func DefaultRankers() []Ranker {
	return []Ranker{
		scoreRanker{name: "max_severity", score: func(feature FeatureVector) float64 { return feature.M5Severity }},
		topologyRanker{},
		scoreRanker{name: "local_evidence", score: func(feature FeatureVector) float64 { return feature.LocalEvidence }},
		scoreRanker{name: "hybrid_v1", score: func(feature FeatureVector) float64 {
			return feature.TopologyF1 * feature.LocalEvidence
		}},
	}
}

func BuildRCA(features FeatureSnapshot, rankers []Ranker) RCASnapshot {
	result := RCASnapshot{
		FeatureSchemaVersion: features.FeatureSchemaVersion,
		State:                features.State,
		PrimarySignal:        features.PrimarySignal,
		ObservedAnomalies:    append([]string(nil), features.ObservedAnomalies...),
		Rankings:             make(map[string]Ranking, len(rankers)),
	}
	for _, ranker := range rankers {
		if ranker == nil {
			continue
		}
		if features.State == StateReady {
			result.Rankings[ranker.Name()] = ranker.Rank(features)
		} else {
			result.Rankings[ranker.Name()] = Ranking{}
		}
	}
	return result
}

type scoredFeature struct {
	feature FeatureVector
	score   float64
}

type scoreRanker struct {
	name  string
	score func(FeatureVector) float64
}

func (ranker scoreRanker) Name() string { return ranker.name }

func (ranker scoreRanker) Rank(snapshot FeatureSnapshot) Ranking {
	values := candidateScores(snapshot, ranker.score)
	sort.Slice(values, func(left, right int) bool {
		if values[left].score != values[right].score {
			return values[left].score > values[right].score
		}
		return values[left].feature.Service < values[right].feature.Service
	})
	return rankingFromScores(values, snapshot.PrimarySignal)
}

type topologyRanker struct{}

func (topologyRanker) Name() string { return "topology_consistency" }

func (topologyRanker) Rank(snapshot FeatureSnapshot) Ranking {
	values := candidateScores(snapshot, func(feature FeatureVector) float64 { return feature.TopologyF1 })
	sort.Slice(values, func(left, right int) bool {
		if values[left].score != values[right].score {
			return values[left].score > values[right].score
		}
		leftStrength := primaryStrength(values[left].feature, snapshot.PrimarySignal)
		rightStrength := primaryStrength(values[right].feature, snapshot.PrimarySignal)
		if leftStrength != rightStrength {
			return leftStrength > rightStrength
		}
		return values[left].feature.Service < values[right].feature.Service
	})
	return rankingFromScores(values, snapshot.PrimarySignal)
}

func candidateScores(snapshot FeatureSnapshot, score func(FeatureVector) float64) []scoredFeature {
	values := make([]scoredFeature, 0)
	for _, feature := range snapshot.Services {
		if !feature.Ready || !feature.Candidate {
			continue
		}
		values = append(values, scoredFeature{feature: feature, score: nonNegativeFinite(score(feature))})
	}
	return values
}

func rankingFromScores(values []scoredFeature, signal PrimarySignal) Ranking {
	result := make(Ranking, 0, len(values))
	for index, value := range values {
		feature := value.feature
		z, strength := primaryValues(feature, signal)
		result = append(result, RankedCandidate{
			Rank:    index + 1,
			Service: feature.Service,
			Score:   value.score,
			Evidence: CandidateEvidence{
				Topology: TopologyEvidence{
					Precision:           feature.TopologyPrecision,
					Recall:              feature.TopologyRecall,
					F1:                  feature.TopologyF1,
					ExpectedAffected:    append([]string(nil), feature.ExpectedAffectedServices...),
					Source:              feature.TopologySource,
					ActiveTraceCoverage: feature.ActiveTopologyTraceCoverage,
				},
				Signal: SignalEvidence{Type: signal, Z: z, Strength: strength},
				Trace: TraceEvidence{
					ExclusiveRatio:      feature.MedianExclusiveRatio,
					ExclusiveDurationMS: feature.MedianExclusiveDurationMS,
					Coverage:            feature.TraceCoverage,
				},
				LocalEvidence: feature.LocalEvidence,
				M5Severity:    feature.M5Severity,
			},
		})
	}
	return result
}

func primaryValues(feature FeatureVector, signal PrimarySignal) (float64, float64) {
	if signal == SignalError {
		return feature.ErrorZ, feature.ErrorStrength
	}
	if signal == SignalLatency {
		return feature.LatencyZ, feature.LatencyStrength
	}
	return 0, 0
}

func primaryStrength(feature FeatureVector, signal PrimarySignal) float64 {
	_, strength := primaryValues(feature, signal)
	return strength
}
