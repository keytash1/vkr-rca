package rca

import (
	"testing"
	"time"

	"vkr-rca/internal/anomaly"
	"vkr-rca/internal/graph"
)

func TestAnomalyObserverUsesOnlyBusinessServerSpans(t *testing.T) {
	detector := newRCATestDetector(t)
	detector.StartBaseline()
	observer := NewAnomalyObserver(detector)

	spans := []graph.Span{
		{ServiceName: "payment", Name: "server", Kind: graph.SpanKindServer, HTTPMethod: "GET", HTTPRoute: "/authorize", HTTPStatus: 200, Duration: 10 * time.Millisecond},
		{ServiceName: "payment", Name: "client", Kind: graph.SpanKindClient, HTTPMethod: "GET", HTTPRoute: "/authorize", HTTPStatus: 502, Duration: 10 * time.Millisecond},
		{ServiceName: "payment", Name: "health", Kind: graph.SpanKindServer, HTTPMethod: "GET", HTTPRoute: "/health", Duration: time.Millisecond},
		{ServiceName: "payment", Name: "debug", Kind: graph.SpanKindServer, HTTPMethod: "POST", HTTPRoute: "/debug/fault", Duration: time.Millisecond},
		{ServiceName: "payment", Name: "GET /fallback", Kind: graph.SpanKindServer, HTTPStatus: 404, Duration: 10 * time.Millisecond},
		{ServiceName: "payment", Name: "status fallback", Kind: graph.SpanKindServer, StatusCode: graph.StatusError, Duration: 10 * time.Millisecond},
	}
	for _, span := range spans {
		observer.ObserveSpan(span)
	}

	snapshot := detector.Baseline()
	if len(snapshot.Operations) != 3 {
		t.Fatalf("operations = %+v", snapshot.Operations)
	}
	if got := snapshot.Operations[0]; got.Operation != "GET /authorize" || got.Errors != 0 {
		t.Fatalf("routed operation = %+v", got)
	}
	if got := snapshot.Operations[1]; got.Operation != "GET /fallback" || got.Errors != 0 {
		t.Fatalf("404 operation = %+v", got)
	}
	if got := snapshot.Operations[2]; got.Operation != "status fallback" || got.Errors != 1 {
		t.Fatalf("status fallback operation = %+v", got)
	}
}

func TestAnomalyObserverClassifiesHTTPFailures(t *testing.T) {
	detector := newRCATestDetector(t)
	detector.StartBaseline()
	observer := NewAnomalyObserver(detector)
	for index, status := range []int64{200, 400, 499, 500, 502} {
		observer.ObserveSpan(graph.Span{
			ServiceName: "orders",
			Name:        "server",
			Kind:        graph.SpanKindServer,
			HTTPMethod:  "POST",
			HTTPRoute:   "/orders",
			HTTPStatus:  status,
			Duration:    time.Duration(index+1) * time.Millisecond,
		})
	}

	operation := detector.Baseline().Operations[0]
	if operation.Samples != 5 || operation.Errors != 2 {
		t.Fatalf("operation = %+v", operation)
	}
}

func newRCATestDetector(t *testing.T) *anomaly.Detector {
	t.Helper()
	detector, err := anomaly.NewDetector(anomaly.Config{
		MinBaselineSamples: 1,
		MaxBaselineSamples: 100,
		CurrentWindowSize:  20,
		MinCurrentSamples:  1,
		LatencyZThreshold:  anomaly.DefaultLatencyZThreshold,
		ErrorZThreshold:    anomaly.DefaultErrorZThreshold,
		ScaleEpsilon:       anomaly.DefaultScaleEpsilon,
	})
	if err != nil {
		t.Fatalf("new detector: %v", err)
	}
	return detector
}
