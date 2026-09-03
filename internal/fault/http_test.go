package fault

import (
	"bytes"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"
)

func TestDebugHTTPAPI(t *testing.T) {
	injector := New()
	handler := NewHandler(injector)

	assertConfigResponse(t, serve(handler, http.MethodGet, "/debug/fault", "", ""), http.StatusOK, Config{})
	assertConfigResponse(t, serve(handler, http.MethodPost, "/debug/fault", `{"latency_ms":700,"error_rate":0.5}`, "application/json; charset=utf-8"), http.StatusOK, Config{LatencyMS: 700, ErrorRate: 0.5})
	assertConfigResponse(t, serve(handler, http.MethodGet, "/debug/fault", "", ""), http.StatusOK, Config{LatencyMS: 700, ErrorRate: 0.5})
	assertConfigResponse(t, serve(handler, http.MethodPost, "/debug/reset", "", ""), http.StatusOK, Config{})
}

func TestDebugHTTPAPIRejectsInvalidRequests(t *testing.T) {
	handler := NewHandler(New())

	tests := []struct {
		name        string
		method      string
		path        string
		body        string
		contentType string
		wantStatus  int
	}{
		{name: "negative latency", method: http.MethodPost, path: "/debug/fault", body: `{"latency_ms":-1,"error_rate":0}`, contentType: "application/json", wantStatus: http.StatusBadRequest},
		{name: "error rate above one", method: http.MethodPost, path: "/debug/fault", body: `{"latency_ms":0,"error_rate":1.1}`, contentType: "application/json", wantStatus: http.StatusBadRequest},
		{name: "unknown field", method: http.MethodPost, path: "/debug/fault", body: `{"latnecy_ms":700}`, contentType: "application/json", wantStatus: http.StatusBadRequest},
		{name: "trailing object", method: http.MethodPost, path: "/debug/fault", body: `{}` + `{}`, contentType: "application/json", wantStatus: http.StatusBadRequest},
		{name: "wrong content type", method: http.MethodPost, path: "/debug/fault", body: `{}`, contentType: "text/plain", wantStatus: http.StatusUnsupportedMediaType},
		{name: "unsupported fault method", method: http.MethodDelete, path: "/debug/fault", wantStatus: http.StatusMethodNotAllowed},
		{name: "unsupported reset method", method: http.MethodGet, path: "/debug/reset", wantStatus: http.StatusMethodNotAllowed},
		{name: "unknown debug endpoint", method: http.MethodGet, path: "/debug/unknown", wantStatus: http.StatusNotFound},
	}

	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			response := serve(handler, test.method, test.path, test.body, test.contentType)
			if response.Code != test.wantStatus {
				t.Fatalf("status = %d, want %d: %s", response.Code, test.wantStatus, response.Body.String())
			}
		})
	}
}

func serve(handler http.Handler, method, path, body, contentType string) *httptest.ResponseRecorder {
	request := httptest.NewRequest(method, path, bytes.NewBufferString(body))
	if contentType != "" {
		request.Header.Set("Content-Type", contentType)
	}
	response := httptest.NewRecorder()
	handler.ServeHTTP(response, request)
	return response
}

func assertConfigResponse(t *testing.T, response *httptest.ResponseRecorder, wantStatus int, want Config) {
	t.Helper()
	if response.Code != wantStatus {
		t.Fatalf("status = %d, want %d: %s", response.Code, wantStatus, response.Body.String())
	}
	var got Config
	if err := json.NewDecoder(response.Body).Decode(&got); err != nil {
		t.Fatalf("decode response: %v", err)
	}
	if got != want {
		t.Fatalf("config = %+v, want %+v", got, want)
	}
}
