package diagnosis

import (
	"reflect"
	"testing"
	"time"
)

func TestAffectedServicesSupportsBranchesAndCycles(t *testing.T) {
	branch := []Edge{
		{Caller: "gateway", Callee: "orders"},
		{Caller: "orders", Callee: "payment"},
		{Caller: "gateway", Callee: "catalog"},
	}
	if got, want := AffectedServices("payment", branch), []string{"gateway", "orders", "payment"}; !reflect.DeepEqual(got, want) {
		t.Fatalf("payment affected = %v, want %v", got, want)
	}
	if got, want := AffectedServices("catalog", branch), []string{"catalog", "gateway"}; !reflect.DeepEqual(got, want) {
		t.Fatalf("catalog affected = %v, want %v", got, want)
	}

	cycle := []Edge{{Caller: "A", Callee: "B"}, {Caller: "B", Callee: "C"}, {Caller: "C", Callee: "A"}}
	if got, want := AffectedServices("A", cycle), []string{"A", "B", "C"}; !reflect.DeepEqual(got, want) {
		t.Fatalf("cycle affected = %v, want %v", got, want)
	}
}

func TestActiveIncidentGraphExcludesHistoricalBranch(t *testing.T) {
	input := activeGraphInput()
	features := BuildFeatures(input)
	if features.TopologySource != TopologyActiveTraces || features.ActiveTopologyTraceCoverage != 1 {
		t.Fatalf("topology selection = source %q coverage %v", features.TopologySource, features.ActiveTopologyTraceCoverage)
	}
	wantEdges := []Edge{{Caller: "gateway", Callee: "orders"}, {Caller: "orders", Callee: "payment"}}
	if !reflect.DeepEqual(features.TopologyEdges, wantEdges) {
		t.Fatalf("active edges = %v, want %v", features.TopologyEdges, wantEdges)
	}
	if featureByService(t, features, "payment").TopologyF1 != 1 {
		t.Fatalf("payment feature = %+v", featureByService(t, features, "payment"))
	}
}

func TestIncompleteActiveTraceCoverageUsesExplicitGlobalFallback(t *testing.T) {
	input := activeGraphInput()
	input.Operations[1].SampleRefs[0].TraceID = "missing-orders"
	input.Operations[2].SampleRefs[0].TraceID = "missing-payment"
	features := BuildFeatures(input)
	if features.TopologySource != TopologyGlobalFallback || features.ActiveTopologyTraceCoverage != 1.0/3.0 {
		t.Fatalf("topology selection = source %q coverage %v", features.TopologySource, features.ActiveTopologyTraceCoverage)
	}
	want := []Edge{
		{Caller: "gateway", Callee: "catalog"},
		{Caller: "gateway", Callee: "orders"},
		{Caller: "orders", Callee: "payment"},
	}
	if !reflect.DeepEqual(features.TopologyEdges, want) {
		t.Fatalf("fallback edges = %v, want %v", features.TopologyEdges, want)
	}
}

func activeGraphInput() Input {
	base := time.Date(2026, 9, 4, 0, 0, 0, 0, time.UTC)
	spans := []TraceSpan{
		{TraceID: "trace", SpanID: "gs", Service: "gateway", Kind: SpanKindServer, StartTime: base, EndTime: base.Add(100 * time.Millisecond)},
		{TraceID: "trace", SpanID: "gc", ParentSpanID: "gs", Service: "gateway", Kind: SpanKindClient, StartTime: base.Add(time.Millisecond), EndTime: base.Add(99 * time.Millisecond)},
		{TraceID: "trace", SpanID: "os", ParentSpanID: "gc", Service: "orders", Kind: SpanKindServer, StartTime: base.Add(2 * time.Millisecond), EndTime: base.Add(98 * time.Millisecond)},
		{TraceID: "trace", SpanID: "oc", ParentSpanID: "os", Service: "orders", Kind: SpanKindClient, StartTime: base.Add(3 * time.Millisecond), EndTime: base.Add(97 * time.Millisecond)},
		{TraceID: "trace", SpanID: "ps", ParentSpanID: "oc", Service: "payment", Kind: SpanKindServer, StartTime: base.Add(4 * time.Millisecond), EndTime: base.Add(96 * time.Millisecond)},
	}
	operation := func(service, spanID string) OperationEvidence {
		return OperationEvidence{
			Service: service, Operation: "GET /operation", Ready: true, CurrentSamples: 1,
			LatencyZ: 10, LatencyAnomalous: true, M5Severity: 3,
			SampleRefs: []SampleRef{{Service: service, Operation: "GET /operation", TraceID: "trace", SpanID: spanID}},
		}
	}
	return Input{
		BaselineState: "frozen", LatencyThreshold: 3.5, ErrorThreshold: 3,
		MinActiveTopologyTraceCoverage: 0.7,
		Services:                       []string{"gateway", "orders", "payment", "catalog"},
		Edges: []Edge{
			{Caller: "gateway", Callee: "orders"},
			{Caller: "orders", Callee: "payment"},
			{Caller: "gateway", Callee: "catalog"},
		},
		Operations: []OperationEvidence{operation("gateway", "gs"), operation("orders", "os"), operation("payment", "ps")},
		Traces:     map[string][]TraceSpan{"trace": spans},
	}
}

func featureByService(t *testing.T, snapshot FeatureSnapshot, service string) FeatureVector {
	t.Helper()
	for _, feature := range snapshot.Services {
		if feature.Service == service {
			return feature
		}
	}
	t.Fatalf("service %q not found in %+v", service, snapshot.Services)
	return FeatureVector{}
}
