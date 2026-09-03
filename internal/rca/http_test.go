package rca

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"

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
