package payment

import (
	"bytes"
	"encoding/json"
	"io"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"

	"vkr-rca/internal/fault"
)

func TestAuthorize(t *testing.T) {
	request := httptest.NewRequest(http.MethodGet, "/payments/authorize", nil)
	response := httptest.NewRecorder()

	handler := newTestHandler(t, fault.New())
	handler.ServeHTTP(response, request)

	if response.Code != http.StatusOK {
		t.Fatalf("status = %d, want %d", response.Code, http.StatusOK)
	}

	var body map[string]string
	if err := json.NewDecoder(response.Body).Decode(&body); err != nil {
		t.Fatalf("decode response: %v", err)
	}
	if body["status"] != "authorized" {
		t.Fatalf("payment status = %q, want authorized", body["status"])
	}
}

func TestAuthorizeAppliesLatency(t *testing.T) {
	injector := fault.New()
	if err := injector.SetConfig(fault.Config{LatencyMS: 40}); err != nil {
		t.Fatalf("set fault: %v", err)
	}
	handler := newTestHandler(t, injector)

	startedAt := time.Now()
	response := httptest.NewRecorder()
	handler.ServeHTTP(response, httptest.NewRequest(http.MethodGet, "/payments/authorize", nil))

	if response.Code != http.StatusOK {
		t.Fatalf("status = %d, want %d", response.Code, http.StatusOK)
	}
	if elapsed := time.Since(startedAt); elapsed < 30*time.Millisecond {
		t.Fatalf("elapsed = %v, want injected latency", elapsed)
	}
}

func TestAuthorizeInjectedError(t *testing.T) {
	injector := fault.New()
	if err := injector.SetConfig(fault.Config{ErrorRate: 1}); err != nil {
		t.Fatalf("set fault: %v", err)
	}
	handler := newTestHandler(t, injector)

	response := httptest.NewRecorder()
	handler.ServeHTTP(response, httptest.NewRequest(http.MethodGet, "/payments/authorize", nil))

	if response.Code != http.StatusInternalServerError {
		t.Fatalf("status = %d, want %d: %s", response.Code, http.StatusInternalServerError, response.Body.String())
	}
	var body map[string]string
	if err := json.NewDecoder(response.Body).Decode(&body); err != nil {
		t.Fatalf("decode response: %v", err)
	}
	if body["error"] != "injected fault" {
		t.Fatalf("error = %q, want injected fault", body["error"])
	}
}

func TestDebugAPIAndHealthBypassFault(t *testing.T) {
	injector := fault.New()
	handler := newTestHandler(t, injector)

	setRequest := httptest.NewRequest(http.MethodPost, "/debug/fault", bytes.NewBufferString(`{"latency_ms":0,"error_rate":1}`))
	setRequest.Header.Set("Content-Type", "application/json")
	setResponse := httptest.NewRecorder()
	handler.ServeHTTP(setResponse, setRequest)
	if setResponse.Code != http.StatusOK {
		t.Fatalf("set status = %d: %s", setResponse.Code, setResponse.Body.String())
	}

	getResponse := httptest.NewRecorder()
	handler.ServeHTTP(getResponse, httptest.NewRequest(http.MethodGet, "/debug/fault", nil))
	assertFaultConfig(t, getResponse, fault.Config{ErrorRate: 1})

	healthResponse := httptest.NewRecorder()
	handler.ServeHTTP(healthResponse, httptest.NewRequest(http.MethodGet, "/health", nil))
	if healthResponse.Code != http.StatusOK {
		t.Fatalf("health status = %d, want %d", healthResponse.Code, http.StatusOK)
	}

	resetResponse := httptest.NewRecorder()
	handler.ServeHTTP(resetResponse, httptest.NewRequest(http.MethodPost, "/debug/reset", nil))
	assertFaultConfig(t, resetResponse, fault.Config{})

	methodResponse := httptest.NewRecorder()
	handler.ServeHTTP(methodResponse, httptest.NewRequest(http.MethodDelete, "/debug/fault", nil))
	if methodResponse.Code != http.StatusMethodNotAllowed {
		t.Fatalf("unsupported method status = %d, want %d", methodResponse.Code, http.StatusMethodNotAllowed)
	}

	invalidRequest := httptest.NewRequest(http.MethodPost, "/debug/fault", bytes.NewBufferString(`{"error_rate":2}`))
	invalidRequest.Header.Set("Content-Type", "application/json")
	invalidResponse := httptest.NewRecorder()
	handler.ServeHTTP(invalidResponse, invalidRequest)
	if invalidResponse.Code != http.StatusBadRequest {
		t.Fatalf("invalid config status = %d, want %d", invalidResponse.Code, http.StatusBadRequest)
	}
}

func TestAuthorizeRejectsUnsupportedMethod(t *testing.T) {
	request := httptest.NewRequest(http.MethodPost, "/payments/authorize", nil)
	response := httptest.NewRecorder()

	handler := newTestHandler(t, fault.New())
	handler.ServeHTTP(response, request)

	if response.Code != http.StatusMethodNotAllowed {
		t.Fatalf("status = %d, want %d", response.Code, http.StatusMethodNotAllowed)
	}
}

func testLogger() *slog.Logger {
	return slog.New(slog.NewTextHandler(io.Discard, nil))
}

func newTestHandler(t *testing.T, injector *fault.Injector) http.Handler {
	t.Helper()
	handler, err := NewHandler(Config{Logger: testLogger(), Fault: injector})
	if err != nil {
		t.Fatalf("create handler: %v", err)
	}
	return handler
}

func assertFaultConfig(t *testing.T, response *httptest.ResponseRecorder, want fault.Config) {
	t.Helper()
	if response.Code != http.StatusOK {
		t.Fatalf("status = %d, want %d: %s", response.Code, http.StatusOK, response.Body.String())
	}
	var got fault.Config
	if err := json.NewDecoder(response.Body).Decode(&got); err != nil {
		t.Fatalf("decode config: %v", err)
	}
	if got != want {
		t.Fatalf("config = %+v, want %+v", got, want)
	}
}
