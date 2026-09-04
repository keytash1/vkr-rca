package diagnosis

import "sort"

func selectTopology(input Input) ([]Edge, TopologySource, float64) {
	activeEdges, coverage := activeIncidentTopology(input.Operations, input.Traces)
	threshold := input.MinActiveTopologyTraceCoverage
	if threshold <= 0 || threshold > 1 {
		threshold = DefaultMinActiveTopologyTraceCoverage
	}
	if coverage >= threshold {
		return activeEdges, TopologyActiveTraces, coverage
	}
	return sortedUniqueEdges(input.Edges), TopologyGlobalFallback, coverage
}

func activeIncidentTopology(operations []OperationEvidence, traces map[string][]TraceSpan) ([]Edge, float64) {
	totalSamples := 0
	analyzedSamples := 0
	validTraces := make(map[string]struct{})
	for _, operation := range operations {
		currentSamples := operation.CurrentSamples
		if currentSamples < len(operation.SampleRefs) {
			currentSamples = len(operation.SampleRefs)
		}
		totalSamples += currentSamples
		for _, ref := range operation.SampleRefs {
			spans := traces[ref.TraceID]
			if containsServerSpan(spans, ref.SpanID) {
				analyzedSamples++
				validTraces[ref.TraceID] = struct{}{}
			}
		}
	}
	coverage := 0.0
	if totalSamples > 0 {
		coverage = clamp01(float64(analyzedSamples) / float64(totalSamples))
	}

	edges := make([]Edge, 0)
	for traceID := range validTraces {
		spans := traces[traceID]
		byID := make(map[string]TraceSpan, len(spans))
		for _, span := range spans {
			byID[span.SpanID] = span
		}
		for _, child := range spans {
			parent, exists := byID[child.ParentSpanID]
			if !exists || parent.Service == "" || child.Service == "" || parent.Service == child.Service {
				continue
			}
			edges = append(edges, Edge{Caller: parent.Service, Callee: child.Service})
		}
	}
	return sortedUniqueEdges(edges), coverage
}

func containsServerSpan(spans []TraceSpan, spanID string) bool {
	for _, span := range spans {
		if span.SpanID == spanID && span.Kind == SpanKindServer {
			return true
		}
	}
	return false
}

func sortedUniqueEdges(edges []Edge) []Edge {
	unique := make(map[Edge]struct{}, len(edges))
	for _, edge := range edges {
		if edge.Caller != "" && edge.Callee != "" && edge.Caller != edge.Callee {
			unique[edge] = struct{}{}
		}
	}
	result := make([]Edge, 0, len(unique))
	for edge := range unique {
		result = append(result, edge)
	}
	sort.Slice(result, func(left, right int) bool {
		if result[left].Caller != result[right].Caller {
			return result[left].Caller < result[right].Caller
		}
		return result[left].Callee < result[right].Callee
	})
	return result
}

func AffectedServices(candidate string, edges []Edge) []string {
	reverse := make(map[string][]string)
	for _, edge := range edges {
		if edge.Caller == "" || edge.Callee == "" {
			continue
		}
		reverse[edge.Callee] = append(reverse[edge.Callee], edge.Caller)
	}
	visited := map[string]struct{}{candidate: {}}
	queue := []string{candidate}
	for len(queue) > 0 {
		service := queue[0]
		queue = queue[1:]
		for _, caller := range reverse[service] {
			if _, exists := visited[caller]; exists {
				continue
			}
			visited[caller] = struct{}{}
			queue = append(queue, caller)
		}
	}
	result := make([]string, 0, len(visited))
	for service := range visited {
		result = append(result, service)
	}
	sort.Strings(result)
	return result
}

func topologyMetrics(predicted, observed []string) (precision, recall, f1 float64) {
	if len(predicted) == 0 || len(observed) == 0 {
		return 0, 0, 0
	}
	observedSet := make(map[string]struct{}, len(observed))
	for _, service := range observed {
		observedSet[service] = struct{}{}
	}
	truePositives := 0
	for _, service := range predicted {
		if _, exists := observedSet[service]; exists {
			truePositives++
		}
	}
	precision = float64(truePositives) / float64(len(predicted))
	recall = float64(truePositives) / float64(len(observed))
	if precision+recall > 0 {
		f1 = 2 * precision * recall / (precision + recall)
	}
	return precision, recall, f1
}

func intersection(values []string, universe map[string]struct{}) []string {
	result := make([]string, 0, len(values))
	for _, value := range values {
		if _, exists := universe[value]; exists {
			result = append(result, value)
		}
	}
	sort.Strings(result)
	return result
}
