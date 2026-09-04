package diagnosis

import (
	"math"
	"sort"
)

type operationTraceStats struct {
	currentSamples            int
	traceSamples              int
	coverage                  float64
	medianExclusiveRatio      float64
	medianExclusiveDurationMS float64
	medianWaitRatio           float64
}

func BuildFeatures(input Input) FeatureSnapshot {
	topologyEdges, topologySource, activeTopologyCoverage := selectTopology(input)
	operations := append([]OperationEvidence(nil), input.Operations...)
	sort.Slice(operations, func(left, right int) bool {
		if operations[left].Service != operations[right].Service {
			return operations[left].Service < operations[right].Service
		}
		return operations[left].Operation < operations[right].Operation
	})

	features := make(map[string]FeatureVector)
	for _, service := range input.Services {
		if service != "" {
			features[service] = FeatureVector{Service: service}
		}
	}
	for _, operation := range operations {
		if operation.Service == "" {
			continue
		}
		feature := features[operation.Service]
		feature.Service = operation.Service
		if !operation.Ready {
			features[operation.Service] = feature
			continue
		}

		feature.Ready = true
		latencyZ := nonNegativeFinite(operation.LatencyZ)
		errorZ := nonNegativeFinite(operation.ErrorZ)
		latencyStrength := Strength(latencyZ, input.LatencyThreshold)
		if feature.SourceOperationLatency == "" || latencyZ > feature.LatencyZ ||
			(latencyZ == feature.LatencyZ && operation.Operation < feature.SourceOperationLatency) {
			feature.LatencyZ = latencyZ
			feature.LatencyStrength = latencyStrength
			feature.SourceOperationLatency = operation.Operation
		}
		if feature.SourceOperationError == "" || errorZ > feature.ErrorZ ||
			(errorZ == feature.ErrorZ && operation.Operation < feature.SourceOperationError) {
			feature.ErrorZ = errorZ
			feature.ErrorStrength = Strength(errorZ, input.ErrorThreshold)
			feature.SourceOperationError = operation.Operation
		}
		feature.LatencyAnomalous = feature.LatencyAnomalous || operation.LatencyAnomalous
		feature.ErrorAnomalous = feature.ErrorAnomalous || operation.ErrorAnomalous
		if severity := nonNegativeFinite(operation.M5Severity); severity > feature.M5Severity {
			feature.M5Severity = severity
		}

		traceStats := analyzeOperationTraces(operation, input.Traces)
		localScore := latencyStrength * traceStats.medianExclusiveRatio * traceStats.coverage
		currentTraceScore := feature.TraceOperationLatencyStrength * feature.MedianExclusiveRatio * feature.TraceCoverage
		if feature.SourceOperationTrace == "" || localScore > currentTraceScore ||
			(localScore == currentTraceScore && operation.Operation < feature.SourceOperationTrace) {
			feature.SourceOperationTrace = operation.Operation
			feature.TraceOperationLatencyStrength = latencyStrength
			feature.CurrentSamples = traceStats.currentSamples
			feature.TraceSamples = traceStats.traceSamples
			feature.TraceCoverage = traceStats.coverage
			feature.MedianExclusiveRatio = traceStats.medianExclusiveRatio
			feature.MedianExclusiveDurationMS = traceStats.medianExclusiveDurationMS
			feature.MedianDownstreamWaitRatio = traceStats.medianWaitRatio
		}
		features[operation.Service] = feature
	}

	serviceNames := make([]string, 0, len(features))
	readySet := make(map[string]struct{})
	primary := SignalNone
	for service, feature := range features {
		serviceNames = append(serviceNames, service)
		if feature.Ready {
			readySet[service] = struct{}{}
		}
		if feature.Ready && feature.ErrorAnomalous {
			primary = SignalError
		}
	}
	if primary == SignalNone {
		for _, feature := range features {
			if feature.Ready && feature.LatencyAnomalous {
				primary = SignalLatency
				break
			}
		}
	}
	sort.Strings(serviceNames)
	readyUniverse := sortedSet(readySet)
	observed := make([]string, 0)
	for _, service := range serviceNames {
		feature := features[service]
		if _, ready := readySet[service]; !ready {
			continue
		}
		if (primary == SignalError && feature.ErrorAnomalous) ||
			(primary == SignalLatency && feature.LatencyAnomalous) {
			observed = append(observed, service)
		}
	}

	result := FeatureSnapshot{
		FeatureSchemaVersion:        FeatureSchemaVersion,
		BaselineState:               input.BaselineState,
		PrimarySignal:               primary,
		TopologySource:              topologySource,
		ActiveTopologyTraceCoverage: activeTopologyCoverage,
		TopologyEdges:               topologyEdges,
		ReadyUniverse:               readyUniverse,
		ObservedAnomalies:           observed,
		Services:                    make([]FeatureVector, 0, len(serviceNames)),
	}
	switch {
	case input.BaselineState != "frozen":
		result.State = StateBaselineNotFrozen
	case len(readyUniverse) == 0:
		result.State = StateInsufficientData
	case primary == SignalNone:
		result.State = StateNoAnomaly
	default:
		result.State = StateReady
	}

	for _, service := range serviceNames {
		feature := features[service]
		feature.PrimarySignal = primary
		feature.TopologySource = topologySource
		feature.ActiveTopologyTraceCoverage = activeTopologyCoverage
		feature.Candidate = containsSorted(observed, service)
		predicted := intersection(AffectedServices(service, topologyEdges), readySet)
		feature.ExpectedAffectedServices = predicted
		feature.TopologyPrecision, feature.TopologyRecall, feature.TopologyF1 = topologyMetrics(predicted, observed)
		switch primary {
		case SignalError:
			feature.LocalEvidence = feature.ErrorStrength
		case SignalLatency:
			feature.LocalEvidence = feature.TraceOperationLatencyStrength * feature.MedianExclusiveRatio * feature.TraceCoverage
		}
		feature.LocalEvidence = clamp01(nonNegativeFinite(feature.LocalEvidence))
		result.Services = append(result.Services, feature)
	}
	return result
}

func Strength(z, threshold float64) float64 {
	z = nonNegativeFinite(z)
	if threshold <= 0 || math.IsNaN(threshold) || math.IsInf(threshold, 0) {
		return 0
	}
	return clamp01(1 - math.Exp(-z/threshold))
}

func analyzeOperationTraces(operation OperationEvidence, traces map[string][]TraceSpan) operationTraceStats {
	stats := operationTraceStats{currentSamples: operation.CurrentSamples}
	if stats.currentSamples < len(operation.SampleRefs) {
		stats.currentSamples = len(operation.SampleRefs)
	}
	ratios := make([]float64, 0, len(operation.SampleRefs))
	durations := make([]float64, 0, len(operation.SampleRefs))
	waitRatios := make([]float64, 0, len(operation.SampleRefs))
	for _, ref := range operation.SampleRefs {
		trace := traces[ref.TraceID]
		measurement, valid := ExclusiveObserved(trace, ref.SpanID)
		if !valid {
			continue
		}
		stats.traceSamples++
		ratios = append(ratios, measurement.ExclusiveRatio)
		durations = append(durations, measurement.ExclusiveObservedDuration)
		waitRatios = append(waitRatios, measurement.DownstreamWaitRatio)
	}
	if stats.currentSamples > 0 {
		stats.coverage = clamp01(float64(stats.traceSamples) / float64(stats.currentSamples))
	}
	stats.medianExclusiveRatio = medianFloat(ratios)
	stats.medianExclusiveDurationMS = medianFloat(durations)
	stats.medianWaitRatio = medianFloat(waitRatios)
	return stats
}

func medianFloat(values []float64) float64 {
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

func nonNegativeFinite(value float64) float64 {
	if value < 0 || math.IsNaN(value) || math.IsInf(value, 0) {
		return 0
	}
	return value
}

func sortedSet(values map[string]struct{}) []string {
	result := make([]string, 0, len(values))
	for value := range values {
		result = append(result, value)
	}
	sort.Strings(result)
	return result
}

func containsSorted(values []string, target string) bool {
	index := sort.SearchStrings(values, target)
	return index < len(values) && values[index] == target
}
