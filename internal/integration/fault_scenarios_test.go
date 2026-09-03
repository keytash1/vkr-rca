package integration_test

import (
	"io"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"sync/atomic"
	"testing"
	"time"

	"vkr-rca/internal/fault"
	"vkr-rca/internal/gateway"
	"vkr-rca/internal/orders"
	"vkr-rca/internal/payment"
	"vkr-rca/internal/platform"
)

func TestPaymentLatencyScenario(t *testing.T) {
	chain := newFaultChain(t, fault.Config{LatencyMS: 60}, fault.Config{})

	startedAt := time.Now()
	response := serveRequest(chain.gateway, "/api/order", "payment-latency")
	elapsed := time.Since(startedAt)

	if response.Code != http.StatusOK {
		t.Fatalf("gateway status = %d, want %d: %s", response.Code, http.StatusOK, response.Body.String())
	}
	if elapsed < 45*time.Millisecond {
		t.Fatalf("end-to-end duration = %v, want Payment latency", elapsed)
	}
	if got := response.Header().Get(platform.RequestIDHeader); got != "payment-latency" {
		t.Fatalf("request ID = %q, want payment-latency", got)
	}
}

func TestOrdersLatencyKeepsPaymentHealthy(t *testing.T) {
	chain := newFaultChain(t, fault.Config{}, fault.Config{LatencyMS: 60})

	startedAt := time.Now()
	response := serveRequest(chain.gateway, "/api/order", "orders-latency")
	elapsed := time.Since(startedAt)
	paymentStartedAt := time.Unix(0, chain.paymentStartedAt.Load())

	if response.Code != http.StatusOK {
		t.Fatalf("gateway status = %d, want %d: %s", response.Code, http.StatusOK, response.Body.String())
	}
	if elapsed < 45*time.Millisecond {
		t.Fatalf("end-to-end duration = %v, want Orders latency", elapsed)
	}
	if delayBeforePayment := paymentStartedAt.Sub(startedAt); delayBeforePayment < 45*time.Millisecond {
		t.Fatalf("Payment started after %v, want Orders-local delay before Payment", delayBeforePayment)
	}
	if got := chain.paymentFault.GetConfig(); got != (fault.Config{}) {
		t.Fatalf("Payment config = %+v, want healthy", got)
	}
}

func TestPaymentErrorPropagates500To502To502(t *testing.T) {
	chain := newFaultChain(t, fault.Config{ErrorRate: 1}, fault.Config{})

	paymentResponse := serveRequest(chain.payment, "/payments/authorize", "payment-error-direct")
	if paymentResponse.Code != http.StatusInternalServerError {
		t.Fatalf("Payment status = %d, want %d", paymentResponse.Code, http.StatusInternalServerError)
	}

	ordersResponse := serveRequest(chain.orders, "/orders/current", "payment-error-orders")
	if ordersResponse.Code != http.StatusBadGateway {
		t.Fatalf("Orders status = %d, want %d", ordersResponse.Code, http.StatusBadGateway)
	}

	gatewayResponse := serveRequest(chain.gateway, "/api/order", "payment-error-chain")
	if gatewayResponse.Code != http.StatusBadGateway {
		t.Fatalf("Gateway status = %d, want %d", gatewayResponse.Code, http.StatusBadGateway)
	}
	if got := gatewayResponse.Header().Get(platform.RequestIDHeader); got != "payment-error-chain" {
		t.Fatalf("request ID = %q, want payment-error-chain", got)
	}
}

type faultChain struct {
	gateway          http.Handler
	orders           http.Handler
	payment          http.Handler
	paymentFault     *fault.Injector
	paymentStartedAt atomic.Int64
}

func newFaultChain(t *testing.T, paymentConfig, ordersConfig fault.Config) *faultChain {
	t.Helper()
	logger := slog.New(slog.NewTextHandler(io.Discard, nil))
	paymentFault := fault.New()
	if err := paymentFault.SetConfig(paymentConfig); err != nil {
		t.Fatalf("set Payment fault: %v", err)
	}
	ordersFault := fault.New()
	if err := ordersFault.SetConfig(ordersConfig); err != nil {
		t.Fatalf("set Orders fault: %v", err)
	}

	paymentHandler, err := payment.NewHandler(payment.Config{Logger: logger, Fault: paymentFault})
	if err != nil {
		t.Fatalf("create Payment handler: %v", err)
	}
	chain := &faultChain{payment: paymentHandler, paymentFault: paymentFault}
	observedPayment := http.HandlerFunc(func(writer http.ResponseWriter, request *http.Request) {
		chain.paymentStartedAt.Store(time.Now().UnixNano())
		paymentHandler.ServeHTTP(writer, request)
	})

	ordersHandler, err := orders.NewHandler(orders.Config{
		PaymentURL: "http://payment",
		Client:     clientFor(observedPayment),
		Logger:     logger,
		Fault:      ordersFault,
	})
	if err != nil {
		t.Fatalf("create Orders handler: %v", err)
	}
	chain.orders = ordersHandler

	gatewayHandler, err := gateway.NewHandler(gateway.Config{
		OrdersURL: "http://orders",
		Client:    clientFor(ordersHandler),
		Logger:    logger,
	})
	if err != nil {
		t.Fatalf("create Gateway handler: %v", err)
	}
	chain.gateway = gatewayHandler
	return chain
}

func serveRequest(handler http.Handler, path, requestID string) *httptest.ResponseRecorder {
	request := httptest.NewRequest(http.MethodGet, path, nil)
	request.Header.Set(platform.RequestIDHeader, requestID)
	response := httptest.NewRecorder()
	handler.ServeHTTP(response, request)
	return response
}
