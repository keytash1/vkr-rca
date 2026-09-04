package rca

import (
	"bytes"
	"encoding/json"
	"net/http"
	"strings"
	"sync"
	"testing"
	"time"

	"vkr-rca/internal/anomaly"
	"vkr-rca/internal/diagnosis"
	"vkr-rca/internal/graph"
)

func TestDiagnosisProviderBuildsActiveTraceFeaturesAndRankings(t *testing.T) {
	store, detector, provider := diagnosisFixture(t)
	_ = store
	_ = detector

	features := provider.Features()
	if features.FeatureSchemaVersion != diagnosis.FeatureSchemaVersion || features.State != diagnosis.StateReady ||
		features.PrimarySignal != diagnosis.SignalLatency || features.TopologySource != diagnosis.TopologyActiveTraces ||
		features.ActiveTopologyTraceCoverage != 1 {
		t.Fatalf("feature snapshot = %+v", features)
	}
	gateway := diagnosisFeature(t, features, "gateway")
	orders := diagnosisFeature(t, features, "orders")
	payment := diagnosisFeature(t, features, "payment")
	if payment.MedianExclusiveRatio <= orders.MedianExclusiveRatio+.5 || payment.MedianExclusiveRatio <= gateway.MedianExclusiveRatio+.5 {
		t.Fatalf("exclusive ratios gateway=%v orders=%v payment=%v", gateway.MedianExclusiveRatio, orders.MedianExclusiveRatio, payment.MedianExclusiveRatio)
	}
	rca := provider.RCA()
	if rca.Rankings["hybrid_v1"][0].Service != "payment" || rca.Rankings["topology_consistency"][0].Service != "payment" {
		t.Fatalf("RCA rankings = %+v", rca.Rankings)
	}
}

func TestDiagnosisHTTPIsDeterministicAndContainsNoGroundTruth(t *testing.T) {
	store, detector, provider := diagnosisFixture(t)
	handler := NewHTTPHandler(store, discardLogger(), detector, provider)

	for _, path := range []string{"/api/features", "/api/rca"} {
		first := serveHTTP(handler, http.MethodGet, path)
		second := serveHTTP(handler, http.MethodGet, path)
		if first.Code != http.StatusOK || !bytes.Equal(first.Body.Bytes(), second.Body.Bytes()) {
			t.Fatalf("%s responses status=%d deterministic=%v", path, first.Code, bytes.Equal(first.Body.Bytes(), second.Body.Bytes()))
		}
		body := first.Body.String()
		for _, forbidden := range []string{"ground_truth", "fault_service", "probability", "confidence", "NaN", "Inf"} {
			if strings.Contains(body, forbidden) {
				t.Fatalf("%s contains forbidden %q: %s", path, forbidden, body)
			}
		}
	}
	if response := serveHTTP(handler, http.MethodPost, "/api/rca"); response.Code != http.StatusMethodNotAllowed {
		t.Fatalf("POST /api/rca status = %d", response.Code)
	}

	var decoded diagnosis.RCASnapshot
	response := serveHTTP(handler, http.MethodGet, "/api/rca")
	if err := json.NewDecoder(response.Body).Decode(&decoded); err != nil {
		t.Fatalf("decode RCA: %v", err)
	}
	if len(decoded.Rankings) != 4 {
		t.Fatalf("rankings = %+v", decoded.Rankings)
	}
}

func TestDiagnosisProviderConcurrentReadsAndIngestion(t *testing.T) {
	store, detector, provider := diagnosisFixture(t)
	var waitGroup sync.WaitGroup
	for worker := 0; worker < 8; worker++ {
		waitGroup.Add(1)
		go func(worker int) {
			defer waitGroup.Done()
			for index := 0; index < 50; index++ {
				traceID := strings.Repeat(string(rune('a'+worker)), 1) + "-" + time.Now().String()
				store.Ingest([]graph.Span{{TraceID: traceID, SpanID: "server", ServiceName: "service", Kind: graph.SpanKindServer, StartTime: time.Now(), EndTime: time.Now().Add(time.Millisecond)}})
				detector.Observe(anomaly.Observation{Key: anomaly.OperationKey{Service: "service", Operation: "GET /op"}, TraceID: traceID, SpanID: "server", Latency: time.Millisecond})
				_ = provider.Features()
				_ = provider.RCA()
			}
		}(worker)
	}
	waitGroup.Wait()
}

func diagnosisFixture(t *testing.T) (*graph.Store, *anomaly.Detector, *DiagnosisProvider) {
	t.Helper()
	store := newReceiverTestStore(t)
	detector := newRCATestDetector(t)
	operations := []anomaly.OperationKey{
		{Service: "gateway", Operation: "GET /api/order"},
		{Service: "orders", Operation: "GET /orders/current"},
		{Service: "payment", Operation: "GET /payments/authorize"},
	}
	detector.StartBaseline()
	for _, key := range operations {
		detector.Observe(anomaly.Observation{Key: key, Latency: time.Millisecond})
	}
	if err := detector.FreezeBaseline(); err != nil {
		t.Fatalf("freeze: %v", err)
	}

	base := time.Date(2026, 9, 4, 0, 0, 0, 0, time.UTC)
	spans := []graph.Span{
		{TraceID: "trace", SpanID: "gs", ServiceName: "gateway", Kind: graph.SpanKindServer, StartTime: base, EndTime: base.Add(100 * time.Millisecond), Duration: 100 * time.Millisecond},
		{TraceID: "trace", SpanID: "gc", ParentSpanID: "gs", ServiceName: "gateway", Kind: graph.SpanKindClient, StartTime: base.Add(time.Millisecond), EndTime: base.Add(99 * time.Millisecond), Duration: 98 * time.Millisecond},
		{TraceID: "trace", SpanID: "os", ParentSpanID: "gc", ServiceName: "orders", Kind: graph.SpanKindServer, StartTime: base.Add(2 * time.Millisecond), EndTime: base.Add(98 * time.Millisecond), Duration: 96 * time.Millisecond},
		{TraceID: "trace", SpanID: "oc", ParentSpanID: "os", ServiceName: "orders", Kind: graph.SpanKindClient, StartTime: base.Add(3 * time.Millisecond), EndTime: base.Add(97 * time.Millisecond), Duration: 94 * time.Millisecond},
		{TraceID: "trace", SpanID: "ps", ParentSpanID: "oc", ServiceName: "payment", Kind: graph.SpanKindServer, StartTime: base.Add(4 * time.Millisecond), EndTime: base.Add(96 * time.Millisecond), Duration: 92 * time.Millisecond},
	}
	store.Ingest(spans)
	for index, spanID := range []string{"gs", "os", "ps"} {
		span := spans[index*2]
		detector.Observe(anomaly.Observation{Key: operations[index], TraceID: "trace", SpanID: spanID, Timestamp: span.EndTime, Latency: span.Duration})
	}
	provider, err := NewDiagnosisProvider(store, detector, diagnosis.DefaultMinActiveTopologyTraceCoverage)
	if err != nil {
		t.Fatalf("new diagnosis provider: %v", err)
	}
	return store, detector, provider
}

func diagnosisFeature(t *testing.T, snapshot diagnosis.FeatureSnapshot, service string) diagnosis.FeatureVector {
	t.Helper()
	for _, feature := range snapshot.Services {
		if feature.Service == service {
			return feature
		}
	}
	t.Fatalf("missing service %q", service)
	return diagnosis.FeatureVector{}
}
