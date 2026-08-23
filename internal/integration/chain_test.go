package integration_test

import (
	"encoding/json"
	"io"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"testing"

	"vkr-rca/internal/gateway"
	"vkr-rca/internal/orders"
	"vkr-rca/internal/payment"
	"vkr-rca/internal/platform"
)

func TestGatewayOrdersPaymentChain(t *testing.T) {
	logger := slog.New(slog.NewTextHandler(io.Discard, nil))
	paymentHandler := payment.NewHandler(logger)

	ordersHandler, err := orders.NewHandler(orders.Config{
		PaymentURL: "http://payment",
		Client:     clientFor(paymentHandler),
		Logger:     logger,
	})
	if err != nil {
		t.Fatalf("create orders handler: %v", err)
	}
	gatewayHandler, err := gateway.NewHandler(gateway.Config{
		OrdersURL: "http://orders",
		Client:    clientFor(ordersHandler),
		Logger:    logger,
	})
	if err != nil {
		t.Fatalf("create gateway handler: %v", err)
	}
	request := httptest.NewRequest(http.MethodGet, "/api/order", nil)
	request.Header.Set(platform.RequestIDHeader, "chain-test")
	recorder := httptest.NewRecorder()
	gatewayHandler.ServeHTTP(recorder, request)
	response := recorder.Result()
	defer response.Body.Close()

	if response.StatusCode != http.StatusOK {
		t.Fatalf("status = %d, want %d", response.StatusCode, http.StatusOK)
	}
	if got := response.Header.Get(platform.RequestIDHeader); got != "chain-test" {
		t.Fatalf("response request ID = %q, want chain-test", got)
	}

	var body struct {
		Service string `json:"service"`
		Order   struct {
			Status  string `json:"status"`
			Payment struct {
				Status string `json:"status"`
			} `json:"payment"`
		} `json:"order"`
	}
	if err := json.NewDecoder(response.Body).Decode(&body); err != nil {
		t.Fatalf("decode response: %v", err)
	}
	if body.Service != "gateway" || body.Order.Status != "confirmed" || body.Order.Payment.Status != "authorized" {
		t.Fatalf("unexpected chain response: %+v", body)
	}
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
