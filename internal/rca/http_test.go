package rca

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"

	"vkr-rca/internal/anomaly"
	"vkr-rca/internal/graph"
)

func TestHTTPGraphTraceAndReset(t *testing.T) {
	store := newReceiverTestStore(t)
	traceID := "01010101010101010101010101010101"
	store.Ingest([]graph.Span{
		{TraceID: traceID, SpanID: "01", ServiceName: "gateway", StartTime: time.Unix(1, 0)},
		{TraceID: traceID, SpanID: "02", ParentSpanID: "01", ServiceName: "orders", StartTime: time.Unix(2, 0)},
	})
	handler := NewHTTPHandler(store, discardLogger())

	graphResponse := serveHTTP(handler, http.MethodGet, "/api/graph")
	if graphResponse.Code != http.StatusOK {
		t.Fatalf("graph status = %d: %s", graphResponse.Code, graphResponse.Body.String())
	}
	var snapshot graph.Snapshot
	if err := json.NewDecoder(graphResponse.Body).Decode(&snapshot); err != nil {
		t.Fatalf("decode graph: %v", err)
	}
	if len(snapshot.Nodes) != 2 || len(snapshot.Edges) != 1 {
		t.Fatalf("graph = %+v", snapshot)
	}

	traceResponse := serveHTTP(handler, http.MethodGet, "/api/traces/"+traceID)
	if traceResponse.Code != http.StatusOK {
		t.Fatalf("trace status = %d: %s", traceResponse.Code, traceResponse.Body.String())
	}

	resetResponse := serveHTTP(handler, http.MethodPost, "/debug/reset")
	if resetResponse.Code != http.StatusOK {
		t.Fatalf("reset status = %d: %s", resetResponse.Code, resetResponse.Body.String())
	}
	afterReset := serveHTTP(handler, http.MethodGet, "/api/graph")
	if err := json.NewDecoder(afterReset.Body).Decode(&snapshot); err != nil {
		t.Fatalf("decode reset graph: %v", err)
	}
	if len(snapshot.Nodes) != 0 || len(snapshot.Edges) != 0 {
		t.Fatalf("graph after reset = %+v", snapshot)
	}
}

func TestHTTPBaselineAndAnomalyLifecycle(t *testing.T) {
	detector := newRCATestDetector(t)
	handler := NewHTTPHandler(newReceiverTestStore(t), discardLogger(), detector)

	if response := serveHTTP(handler, http.MethodPost, "/debug/baseline/freeze"); response.Code != http.StatusConflict {
		t.Fatalf("freeze empty status = %d: %s", response.Code, response.Body.String())
	}
	if response := serveHTTP(handler, http.MethodPost, "/debug/baseline/start"); response.Code != http.StatusOK {
		t.Fatalf("start status = %d: %s", response.Code, response.Body.String())
	}
	detector.Observe(anomaly.Observation{
		Key:     anomaly.OperationKey{Service: "payment", Operation: "GET /authorize"},
		Latency: 10 * time.Millisecond,
	})
	if response := serveHTTP(handler, http.MethodPost, "/debug/baseline/freeze"); response.Code != http.StatusOK {
		t.Fatalf("freeze status = %d: %s", response.Code, response.Body.String())
	}
	detector.Observe(anomaly.Observation{
		Key:     anomaly.OperationKey{Service: "payment", Operation: "GET /authorize"},
		Latency: time.Second,
	})

	anomaliesResponse := serveHTTP(handler, http.MethodGet, "/api/anomalies")
	var snapshot anomaly.AnomalySnapshot
	if err := json.NewDecoder(anomaliesResponse.Body).Decode(&snapshot); err != nil {
		t.Fatalf("decode anomalies: %v", err)
	}
	if len(snapshot.Operations) != 1 || !snapshot.Operations[0].LatencyAnomalous {
		t.Fatalf("anomalies = %+v", snapshot)
	}
	if response := serveHTTP(handler, http.MethodPost, "/debug/anomaly/reset"); response.Code != http.StatusOK {
		t.Fatalf("reset current status = %d: %s", response.Code, response.Body.String())
	}
	if detector.Baseline().State != anomaly.StateFrozen || detector.Anomalies().Operations[0].CurrentSamples != 0 {
		t.Fatalf("reset did not preserve baseline and clear current")
	}

	tests := []struct {
		method string
		path   string
	}{
		{http.MethodPost, "/api/baseline"},
		{http.MethodPost, "/api/anomalies"},
		{http.MethodGet, "/debug/baseline/start"},
		{http.MethodGet, "/debug/baseline/freeze"},
		{http.MethodGet, "/debug/anomaly/reset"},
	}
	for _, test := range tests {
		if response := serveHTTP(handler, test.method, test.path); response.Code != http.StatusMethodNotAllowed {
			t.Errorf("%s %s status = %d", test.method, test.path, response.Code)
		}
	}
}

func TestHTTPMethodsHealthAndMissingTrace(t *testing.T) {
	handler := NewHTTPHandler(newReceiverTestStore(t), discardLogger())
	tests := []struct {
		method string
		path   string
		status int
	}{
		{method: http.MethodGet, path: "/health", status: http.StatusOK},
		{method: http.MethodPost, path: "/api/graph", status: http.StatusMethodNotAllowed},
		{method: http.MethodPost, path: "/api/traces/missing", status: http.StatusMethodNotAllowed},
		{method: http.MethodGet, path: "/api/traces/missing", status: http.StatusNotFound},
		{method: http.MethodGet, path: "/api/traces/", status: http.StatusNotFound},
		{method: http.MethodGet, path: "/debug/reset", status: http.StatusMethodNotAllowed},
	}
	for _, test := range tests {
		response := serveHTTP(handler, test.method, test.path)
		if response.Code != test.status {
			t.Errorf("%s %s status = %d, want %d", test.method, test.path, response.Code, test.status)
		}
	}
}

func serveHTTP(handler http.Handler, method, path string) *httptest.ResponseRecorder {
	response := httptest.NewRecorder()
	handler.ServeHTTP(response, httptest.NewRequest(method, path, nil))
	return response
}
