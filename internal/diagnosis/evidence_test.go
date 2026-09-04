package diagnosis

import (
	"math"
	"reflect"
	"testing"
	"time"
)

func TestStrengthIsBoundedMonotonicEvidence(t *testing.T) {
	if Strength(0, 3.5) != 0 {
		t.Fatal("zero z did not produce zero strength")
	}
	if got, want := Strength(3.5, 3.5), 1-math.Exp(-1); math.Abs(got-want) > 1e-12 {
		t.Fatalf("threshold strength = %v, want %v", got, want)
	}
	if got := Strength(60, 3.5); got <= 0.99 || got > 1 {
		t.Fatalf("large-z strength = %v", got)
	}
	if Strength(math.Inf(1), 3.5) != 0 || Strength(1, 0) != 0 {
		t.Fatal("invalid strength input did not safely return zero")
	}
}

func TestTopologyConsistencyPatterns(t *testing.T) {
	edges := []Edge{{Caller: "gateway", Callee: "orders"}, {Caller: "orders", Callee: "payment"}}
	tests := []struct {
		name      string
		anomalous []string
		ready     []string
		wantTop   string
		wantF1    map[string]float64
	}{
		{
			name: "payment", anomalous: []string{"gateway", "orders", "payment"}, ready: []string{"gateway", "orders", "payment"}, wantTop: "payment",
			wantF1: map[string]float64{"gateway": 0.5, "orders": 0.8, "payment": 1},
		},
		{
			name: "orders", anomalous: []string{"gateway", "orders"}, ready: []string{"gateway", "orders", "payment"}, wantTop: "orders",
			wantF1: map[string]float64{"gateway": 2.0 / 3.0, "orders": 1, "payment": 0.8},
		},
		{
			name: "gateway", anomalous: []string{"gateway"}, ready: []string{"gateway", "orders", "payment"}, wantTop: "gateway",
			wantF1: map[string]float64{"gateway": 1},
		},
		{
			name: "incomplete payment", anomalous: []string{"gateway", "orders"}, ready: []string{"gateway", "orders"}, wantTop: "orders",
			wantF1: map[string]float64{"orders": 1, "payment": 1},
		},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			features := BuildFeatures(patternInput(edges, test.ready, test.anomalous))
			for service, want := range test.wantF1 {
				if got := featureByService(t, features, service).TopologyF1; math.Abs(got-want) > 1e-12 {
					t.Errorf("%s f1 = %v, want %v", service, got, want)
				}
			}
			ranking := topologyRanker{}.Rank(features)
			if len(ranking) == 0 || ranking[0].Service != test.wantTop {
				t.Fatalf("ranking = %+v, want top %s", ranking, test.wantTop)
			}
		})
	}
}

func TestFalsePositiveBranchLowersTopologyRecall(t *testing.T) {
	edges := []Edge{
		{Caller: "gateway", Callee: "orders"},
		{Caller: "orders", Callee: "payment"},
		{Caller: "gateway", Callee: "catalog"},
	}
	features := BuildFeatures(patternInput(
		edges,
		[]string{"catalog", "gateway", "orders", "payment"},
		[]string{"catalog", "gateway", "orders", "payment"},
	))
	payment := featureByService(t, features, "payment")
	if payment.TopologyPrecision != 1 || payment.TopologyRecall != 0.75 || payment.TopologyF1 >= 1 {
		t.Fatalf("payment topology with false positive = %+v", payment)
	}
}

func TestErrorFirstPrimarySignalAndOperationAggregation(t *testing.T) {
	input := patternInput(
		[]Edge{{Caller: "gateway", Callee: "orders"}},
		[]string{"gateway", "orders"},
		[]string{"gateway", "orders"},
	)
	input.Operations[0].LatencyZ = 50
	input.Operations[0].LatencyAnomalous = true
	input.Operations[0].ErrorZ = 8
	input.Operations[0].ErrorAnomalous = true
	for index := range input.Operations {
		if input.Operations[index].Service == "orders" {
			input.Operations[index].ErrorZ = 8
			input.Operations[index].ErrorAnomalous = true
		}
	}
	input.Operations = append(input.Operations, OperationEvidence{
		Service: "gateway", Operation: "GET /secondary", Ready: true, CurrentSamples: 20,
		LatencyZ: 60, ErrorZ: 2, LatencyAnomalous: true, M5Severity: 17,
	})
	features := BuildFeatures(input)
	if features.PrimarySignal != SignalError || !reflect.DeepEqual(features.ObservedAnomalies, []string{"gateway", "orders"}) {
		t.Fatalf("primary signal snapshot = %+v", features)
	}
	gateway := featureByService(t, features, "gateway")
	if gateway.LatencyZ != 60 || gateway.SourceOperationLatency != "GET /secondary" || gateway.ErrorZ != 8 {
		t.Fatalf("aggregated gateway evidence = %+v", gateway)
	}
}

func TestRCAStates(t *testing.T) {
	input := patternInput(nil, []string{"gateway"}, nil)
	input.BaselineState = "collecting"
	if state := BuildFeatures(input).State; state != StateBaselineNotFrozen {
		t.Fatalf("collecting state = %q", state)
	}
	input.BaselineState = "frozen"
	input.Operations[0].Ready = false
	if state := BuildFeatures(input).State; state != StateInsufficientData {
		t.Fatalf("insufficient state = %q", state)
	}
	input.Operations[0].Ready = true
	if state := BuildFeatures(input).State; state != StateNoAnomaly {
		t.Fatalf("healthy state = %q", state)
	}
	if rankings := BuildRCA(BuildFeatures(input), DefaultRankers()).Rankings; len(rankings["hybrid_v1"]) != 0 {
		t.Fatalf("healthy rankings = %+v", rankings)
	}
}

func TestOrdersLocalLatencyProducesStrongOrdersLocalEvidence(t *testing.T) {
	base := time.Unix(0, 0)
	input := Input{
		BaselineState: "frozen", LatencyThreshold: 3.5, ErrorThreshold: 3,
		MinActiveTopologyTraceCoverage: .7,
		Services:                       []string{"gateway", "orders", "payment"},
		Edges:                          []Edge{{Caller: "gateway", Callee: "orders"}, {Caller: "orders", Callee: "payment"}},
		Traces: map[string][]TraceSpan{"orders-latency": {
			{TraceID: "orders-latency", SpanID: "gs", Service: "gateway", Kind: SpanKindServer, StartTime: base, EndTime: base.Add(704 * time.Millisecond)},
			{TraceID: "orders-latency", SpanID: "gc", ParentSpanID: "gs", Service: "gateway", Kind: SpanKindClient, StartTime: base.Add(time.Millisecond), EndTime: base.Add(703 * time.Millisecond)},
			{TraceID: "orders-latency", SpanID: "os", ParentSpanID: "gc", Service: "orders", Kind: SpanKindServer, StartTime: base.Add(2 * time.Millisecond), EndTime: base.Add(702 * time.Millisecond)},
			{TraceID: "orders-latency", SpanID: "oc", ParentSpanID: "os", Service: "orders", Kind: SpanKindClient, StartTime: base.Add(700 * time.Millisecond), EndTime: base.Add(702 * time.Millisecond)},
			{TraceID: "orders-latency", SpanID: "ps", ParentSpanID: "oc", Service: "payment", Kind: SpanKindServer, StartTime: base.Add(700*time.Millisecond + 250*time.Microsecond), EndTime: base.Add(701*time.Millisecond + 750*time.Microsecond)},
		}},
	}
	for _, item := range []struct {
		service string
		spanID  string
		anomaly bool
	}{
		{service: "gateway", spanID: "gs", anomaly: true},
		{service: "orders", spanID: "os", anomaly: true},
		{service: "payment", spanID: "ps", anomaly: false},
	} {
		input.Operations = append(input.Operations, OperationEvidence{
			Service: item.service, Operation: "GET /operation", Ready: true, CurrentSamples: 1,
			LatencyZ: 20, LatencyAnomalous: item.anomaly, M5Severity: 5,
			SampleRefs: []SampleRef{{Service: item.service, Operation: "GET /operation", TraceID: "orders-latency", SpanID: item.spanID}},
		})
	}
	features := BuildFeatures(input)
	gateway := featureByService(t, features, "gateway")
	orders := featureByService(t, features, "orders")
	payment := featureByService(t, features, "payment")
	if orders.MedianExclusiveRatio < .9 || orders.LocalEvidence <= gateway.LocalEvidence+.5 {
		t.Fatalf("local evidence gateway=%+v orders=%+v", gateway, orders)
	}
	if payment.Candidate || payment.LocalEvidence == 0 {
		t.Fatalf("healthy leaf candidate/evidence = %+v", payment)
	}
	if ranking := BuildRCA(features, DefaultRankers()).Rankings["hybrid_v1"]; ranking[0].Service != "orders" {
		t.Fatalf("hybrid ranking = %+v", ranking)
	}
}

func patternInput(edges []Edge, ready, anomalous []string) Input {
	readySet := make(map[string]struct{}, len(ready))
	for _, service := range ready {
		readySet[service] = struct{}{}
	}
	anomalySet := make(map[string]struct{}, len(anomalous))
	for _, service := range anomalous {
		anomalySet[service] = struct{}{}
	}
	services := []string{"gateway", "orders", "payment"}
	for _, service := range append(append([]string(nil), ready...), anomalous...) {
		found := false
		for _, existing := range services {
			if existing == service {
				found = true
			}
		}
		if !found {
			services = append(services, service)
		}
	}
	operations := make([]OperationEvidence, 0, len(services))
	for _, service := range services {
		_, isReady := readySet[service]
		_, isAnomalous := anomalySet[service]
		operations = append(operations, OperationEvidence{
			Service: service, Operation: "GET /operation", Ready: isReady, CurrentSamples: 20,
			LatencyZ: 5, LatencyAnomalous: isAnomalous, M5Severity: 2,
		})
	}
	return Input{
		BaselineState: "frozen", LatencyThreshold: 3.5, ErrorThreshold: 3,
		MinActiveTopologyTraceCoverage: 0.7,
		Services:                       services, Edges: edges, Operations: operations,
	}
}
