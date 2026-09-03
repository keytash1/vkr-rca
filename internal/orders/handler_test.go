package orders

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
	"vkr-rca/internal/platform"
)

func TestCurrentOrderCallsPayment(t *testing.T) {
	const requestID = "test-request-id"
	payment := http.HandlerFunc(func(writer http.ResponseWriter, request *http.Request) {
		if request.URL.Path != "/payments/authorize" {
			t.Errorf("payment path = %q", request.URL.Path)
		}
		if got := request.Header.Get(platform.RequestIDHeader); got != requestID {
			t.Errorf("request ID = %q, want %q", got, requestID)
		}
		platform.WriteJSON(writer, http.StatusOK, map[string]string{
			"provider": "payment",
			"status":   "authorized",
		})
	})

	handler, err := NewHandler(Config{
		PaymentURL: "http://payment",
		Client:     clientFor(payment),
		Logger:     testLogger(),
		Fault:      fault.New(),
	})
	if err != nil {
		t.Fatalf("create handler: %v", err)
	}

	request := httptest.NewRequest(http.MethodGet, "/orders/current", nil)
	request.Header.Set(platform.RequestIDHeader, requestID)
	response := httptest.NewRecorder()
	handler.ServeHTTP(response, request)

	if response.Code != http.StatusOK {
		t.Fatalf("status = %d, want %d: %s", response.Code, http.StatusOK, response.Body.String())
	}

	var body orderResponse
	if err := json.NewDecoder(response.Body).Decode(&body); err != nil {
		t.Fatalf("decode response: %v", err)
	}
	if body.Status != "confirmed" || body.Payment.Status != "authorized" {
		t.Fatalf("unexpected response: %+v", body)
	}
}

func TestCurrentOrderAppliesLatencyBeforePayment(t *testing.T) {
	paymentCalledAt := time.Time{}
	payment := http.HandlerFunc(func(writer http.ResponseWriter, _ *http.Request) {
		paymentCalledAt = time.Now()
		platform.WriteJSON(writer, http.StatusOK, paymentResponse{Provider: "payment", Status: "authorized"})
	})
	injector := fault.New()
	if err := injector.SetConfig(fault.Config{LatencyMS: 40}); err != nil {
		t.Fatalf("set fault: %v", err)
	}
	handler := newOrdersTestHandler(t, payment, injector)

	startedAt := time.Now()
	response := httptest.NewRecorder()
	handler.ServeHTTP(response, httptest.NewRequest(http.MethodGet, "/orders/current", nil))

	if response.Code != http.StatusOK {
		t.Fatalf("status = %d, want %d: %s", response.Code, http.StatusOK, response.Body.String())
	}
	if delayBeforePayment := paymentCalledAt.Sub(startedAt); delayBeforePayment < 30*time.Millisecond {
		t.Fatalf("payment called after %v, want Orders delay before downstream call", delayBeforePayment)
	}
}

func TestCurrentOrderInjectedErrorSkipsPayment(t *testing.T) {
	paymentCalled := false
	payment := http.HandlerFunc(func(writer http.ResponseWriter, _ *http.Request) {
		paymentCalled = true
		platform.WriteJSON(writer, http.StatusOK, paymentResponse{Provider: "payment", Status: "authorized"})
	})
	injector := fault.New()
	if err := injector.SetConfig(fault.Config{ErrorRate: 1}); err != nil {
		t.Fatalf("set fault: %v", err)
	}
	handler := newOrdersTestHandler(t, payment, injector)

	response := httptest.NewRecorder()
	handler.ServeHTTP(response, httptest.NewRequest(http.MethodGet, "/orders/current", nil))

	if response.Code != http.StatusInternalServerError {
		t.Fatalf("status = %d, want %d", response.Code, http.StatusInternalServerError)
	}
	if paymentCalled {
		t.Fatal("payment was called after injected Orders error")
	}
}

func TestDebugAPIAndHealthBypassFault(t *testing.T) {
	payment := http.HandlerFunc(func(writer http.ResponseWriter, _ *http.Request) {
		platform.WriteJSON(writer, http.StatusOK, paymentResponse{Provider: "payment", Status: "authorized"})
	})
	injector := fault.New()
	handler := newOrdersTestHandler(t, payment, injector)

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

	unknownFieldRequest := httptest.NewRequest(http.MethodPost, "/debug/fault", bytes.NewBufferString(`{"latnecy_ms":700}`))
	unknownFieldRequest.Header.Set("Content-Type", "application/json")
	unknownFieldResponse := httptest.NewRecorder()
	handler.ServeHTTP(unknownFieldResponse, unknownFieldRequest)
	if unknownFieldResponse.Code != http.StatusBadRequest {
		t.Fatalf("unknown field status = %d, want %d", unknownFieldResponse.Code, http.StatusBadRequest)
	}
}

func TestCurrentOrderMapsPaymentFailureToBadGateway(t *testing.T) {
	payment := http.HandlerFunc(func(writer http.ResponseWriter, _ *http.Request) {
		http.Error(writer, "failed", http.StatusInternalServerError)
	})

	handler, err := NewHandler(Config{
		PaymentURL: "http://payment",
		Client:     clientFor(payment),
		Logger:     testLogger(),
		Fault:      fault.New(),
	})
	if err != nil {
		t.Fatalf("create handler: %v", err)
	}

	response := httptest.NewRecorder()
	handler.ServeHTTP(response, httptest.NewRequest(http.MethodGet, "/orders/current", nil))

	if response.Code != http.StatusBadGateway {
		t.Fatalf("status = %d, want %d", response.Code, http.StatusBadGateway)
	}
}

func TestNewHandlerRejectsInvalidPaymentURL(t *testing.T) {
	_, err := NewHandler(Config{
		PaymentURL: "payment:8082",
		Client:     &http.Client{},
		Logger:     testLogger(),
		Fault:      fault.New(),
	})
	if err == nil {
		t.Fatal("expected invalid payment URL error")
	}
}

func testLogger() *slog.Logger {
	return slog.New(slog.NewTextHandler(io.Discard, nil))
}

type roundTripperFunc func(*http.Request) (*http.Response, error)

func (function roundTripperFunc) RoundTrip(request *http.Request) (*http.Response, error) {
	return function(request)
}

func clientFor(handler http.Handler) *http.Client {
	return &http.Client{Transport: roundTripperFunc(func(request *http.Request) (*http.Response, error) {
		response := httptest.NewRecorder()
		handler.ServeHTTP(response, request)
		return response.Result(), nil
	})}
}

func newOrdersTestHandler(t *testing.T, payment http.Handler, injector *fault.Injector) http.Handler {
	t.Helper()
	handler, err := NewHandler(Config{
		PaymentURL: "http://payment",
		Client:     clientFor(payment),
		Logger:     testLogger(),
		Fault:      injector,
	})
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
