package gateway

import (
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

func TestOrderCallsOrdersService(t *testing.T) {
	const requestID = "test-request-id"
	orders := http.HandlerFunc(func(writer http.ResponseWriter, request *http.Request) {
		if request.URL.Path != "/orders/current" {
			t.Errorf("orders path = %q", request.URL.Path)
		}
		if got := request.Header.Get(platform.RequestIDHeader); got != requestID {
			t.Errorf("request ID = %q, want %q", got, requestID)
		}
		platform.WriteJSON(writer, http.StatusOK, map[string]any{
			"order_id": "demo-order",
			"status":   "confirmed",
			"payment": map[string]string{
				"provider": "payment",
				"status":   "authorized",
			},
		})
	})

	handler, err := NewHandler(Config{
		OrdersURL: "http://orders",
		Client:    clientFor(orders),
		Logger:    testLogger(),
		Fault:     fault.New(),
	})
	if err != nil {
		t.Fatalf("create handler: %v", err)
	}

	request := httptest.NewRequest(http.MethodGet, "/api/order", nil)
	request.Header.Set(platform.RequestIDHeader, requestID)
	response := httptest.NewRecorder()
	handler.ServeHTTP(response, request)

	if response.Code != http.StatusOK {
		t.Fatalf("status = %d, want %d: %s", response.Code, http.StatusOK, response.Body.String())
	}

	var body gatewayResponse
	if err := json.NewDecoder(response.Body).Decode(&body); err != nil {
		t.Fatalf("decode response: %v", err)
	}
	if body.Service != "gateway" || body.Order.Payment.Status != "authorized" {
		t.Fatalf("unexpected response: %+v", body)
	}
}

func TestOrderMapsOrdersFailureToBadGateway(t *testing.T) {
	orders := http.HandlerFunc(func(writer http.ResponseWriter, _ *http.Request) {
		http.Error(writer, "failed", http.StatusServiceUnavailable)
	})

	handler, err := NewHandler(Config{
		OrdersURL: "http://orders",
		Client:    clientFor(orders),
		Logger:    testLogger(),
		Fault:     fault.New(),
	})
	if err != nil {
		t.Fatalf("create handler: %v", err)
	}

	response := httptest.NewRecorder()
	handler.ServeHTTP(response, httptest.NewRequest(http.MethodGet, "/api/order", nil))

	if response.Code != http.StatusBadGateway {
		t.Fatalf("status = %d, want %d", response.Code, http.StatusBadGateway)
	}
}

func TestGatewayLatencyIsAppliedBeforeCallingOrders(t *testing.T) {
	injector := fault.New()
	if err := injector.SetConfig(fault.Config{LatencyMS: 30}); err != nil {
		t.Fatalf("set fault: %v", err)
	}
	var calledAt time.Time
	orders := http.HandlerFunc(func(writer http.ResponseWriter, _ *http.Request) {
		calledAt = time.Now()
		platform.WriteJSON(writer, http.StatusOK, map[string]any{
			"order_id": "demo-order", "status": "confirmed",
			"payment": map[string]string{"provider": "payment", "status": "authorized"},
		})
	})
	handler, err := NewHandler(Config{OrdersURL: "http://orders", Client: clientFor(orders), Logger: testLogger(), Fault: injector})
	if err != nil {
		t.Fatalf("create handler: %v", err)
	}
	started := time.Now()
	response := httptest.NewRecorder()
	handler.ServeHTTP(response, httptest.NewRequest(http.MethodGet, "/api/order", nil))
	if response.Code != http.StatusOK || calledAt.Sub(started) < 20*time.Millisecond {
		t.Fatalf("status=%d orders called after %v", response.Code, calledAt.Sub(started))
	}
}

func TestGatewayErrorStopsBeforeOrders(t *testing.T) {
	injector := fault.New()
	if err := injector.SetConfig(fault.Config{ErrorRate: 1}); err != nil {
		t.Fatalf("set fault: %v", err)
	}
	ordersCalls := 0
	orders := http.HandlerFunc(func(http.ResponseWriter, *http.Request) { ordersCalls++ })
	handler, err := NewHandler(Config{OrdersURL: "http://orders", Client: clientFor(orders), Logger: testLogger(), Fault: injector})
	if err != nil {
		t.Fatalf("create handler: %v", err)
	}
	response := httptest.NewRecorder()
	handler.ServeHTTP(response, httptest.NewRequest(http.MethodGet, "/api/order", nil))
	if response.Code != http.StatusInternalServerError || ordersCalls != 0 {
		t.Fatalf("status=%d orders calls=%d", response.Code, ordersCalls)
	}
}

func TestGatewayRequiresFaultInjector(t *testing.T) {
	_, err := NewHandler(Config{OrdersURL: "http://orders", Client: clientFor(http.NotFoundHandler()), Logger: testLogger()})
	if err == nil {
		t.Fatal("missing fault injector was accepted")
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
