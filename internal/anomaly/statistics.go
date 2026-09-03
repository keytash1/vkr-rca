package anomaly

import (
	"math"
	"sort"
	"time"
)

const madConsistencyFactor = 1.4826

type latencyStats struct {
	rawMedian float64
	rawP95    float64
	logMedian float64
	logMAD    float64
	scale     float64
}

func calculateLatencyStats(observations []Observation, epsilon float64) latencyStats {
	raw := make([]float64, 0, len(observations))
	transformed := make([]float64, 0, len(observations))
	for _, observation := range observations {
		latencyMS := float64(observation.Latency) / float64(time.Millisecond)
		if latencyMS < 0 {
			latencyMS = 0
		}
		raw = append(raw, latencyMS)
		transformed = append(transformed, math.Log1p(latencyMS))
	}

	logMedian := median(transformed)
	deviations := make([]float64, 0, len(transformed))
	for _, value := range transformed {
		deviations = append(deviations, math.Abs(value-logMedian))
	}
	mad := median(deviations)
	return latencyStats{
		rawMedian: median(raw),
		rawP95:    percentileNearestRank(raw, 0.95),
		logMedian: logMedian,
		logMAD:    mad,
		scale:     math.Max(madConsistencyFactor*mad, epsilon),
	}
}

func median(values []float64) float64 {
	if len(values) == 0 {
		return 0
	}
	sorted := append([]float64(nil), values...)
	sort.Float64s(sorted)
	middle := len(sorted) / 2
	if len(sorted)%2 == 1 {
		return sorted[middle]
	}
	return (sorted[middle-1] + sorted[middle]) / 2
}

func percentileNearestRank(values []float64, quantile float64) float64 {
	if len(values) == 0 {
		return 0
	}
	sorted := append([]float64(nil), values...)
	sort.Float64s(sorted)
	rank := int(math.Ceil(quantile*float64(len(sorted)))) - 1
	if rank < 0 {
		rank = 0
	}
	if rank >= len(sorted) {
		rank = len(sorted) - 1
	}
	return sorted[rank]
}

func smoothedBaselineErrorRate(errors, requests int) float64 {
	if requests < 0 || errors < 0 || errors > requests {
		return 0
	}
	return (float64(errors) + 0.5) / (float64(requests) + 1)
}

func errorRateZ(baselineErrors, baselineRequests, currentErrors, currentRequests int) float64 {
	if baselineRequests <= 0 || currentRequests <= 0 || baselineErrors < 0 || currentErrors < 0 ||
		baselineErrors > baselineRequests || currentErrors > currentRequests {
		return 0
	}

	baselineTrials := float64(baselineRequests) + 1
	baselineSuccesses := float64(baselineErrors) + 0.5
	currentTrials := float64(currentRequests)
	currentSuccesses := float64(currentErrors)
	p0 := baselineSuccesses / baselineTrials
	p1 := currentSuccesses / currentTrials
	if p1 <= p0 {
		return 0
	}

	pooled := (baselineSuccesses + currentSuccesses) / (baselineTrials + currentTrials)
	standardError := math.Sqrt(pooled * (1 - pooled) * (1/baselineTrials + 1/currentTrials))
	if standardError <= 0 || math.IsNaN(standardError) || math.IsInf(standardError, 0) {
		return 0
	}
	result := (p1 - p0) / standardError
	if result < 0 || math.IsNaN(result) || math.IsInf(result, 0) {
		return 0
	}
	return result
}
