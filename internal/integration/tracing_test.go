package integration_test

import (
	"context"
	"io"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"testing"

	"go.opentelemetry.io/otel"
	"go.opentelemetry.io/otel/propagation"
	sdktrace "go.opentelemetry.io/otel/sdk/trace"
	"go.opentelemetry.io/otel/sdk/trace/tracetest"
	"go.opentelemetry.io/otel/trace"
	"vkr-rca/internal/fault"
	"vkr-rca/internal/gateway"
	"vkr-rca/internal/orders"
	"vkr-rca/internal/payment"
	"vkr-rca/internal/platform"
	"vkr-rca/internal/telemetry"
)

func TestDistributedTracePropagation(t *testing.T) {
	previousProvider := otel.GetTracerProvider()
	previousPropagator := otel.GetTextMapPropagator()
	recorder := tracetest.NewSpanRecorder()
	provider := sdktrace.NewTracerProvider(
		sdktrace.WithSpanProcessor(recorder),
		sdktrace.WithSampler(sdktrace.AlwaysSample()),
	)
	otel.SetTracerProvider(provider)
	otel.SetTextMapPropagator(telemetry.Propagator())
	t.Cleanup(func() {
		_ = provider.Shutdown(context.Background())
		otel.SetTracerProvider(previousProvider)
		otel.SetTextMapPropagator(previousPropagator)
	})

	logger := slog.New(slog.NewTextHandler(io.Discard, nil))
	paymentFault := fault.New()
	if err := paymentFault.SetConfig(fault.Config{LatencyMS: 1}); err != nil {
		t.Fatalf("set Payment fault: %v", err)
	}
	paymentApplication, err := payment.NewHandler(payment.Config{Logger: logger, Fault: paymentFault})
	if err != nil {
		t.Fatalf("create payment handler: %v", err)
	}
	paymentHandler := telemetry.InstrumentHandler("payment", paymentApplication)
	paymentClient, paymentTraceparent := instrumentedClientFor(paymentHandler)

	ordersApplication, err := orders.NewHandler(orders.Config{
		PaymentURL: "http://payment",
		Client:     paymentClient,
		Logger:     logger,
		Fault:      fault.New(),
	})
	if err != nil {
		t.Fatalf("create orders handler: %v", err)
	}
	ordersHandler := telemetry.InstrumentHandler("orders", ordersApplication)
	ordersClient, ordersTraceparent := instrumentedClientFor(ordersHandler)

	gatewayApplication, err := gateway.NewHandler(gateway.Config{
		OrdersURL: "http://orders",
		Client:    ordersClient,
		Logger:    logger,
		Fault:     fault.New(),
	})
	if err != nil {
		t.Fatalf("create gateway handler: %v", err)
	}
	gatewayHandler := telemetry.InstrumentHandler("gateway", gatewayApplication)

	traceID := trace.TraceID{1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16}
	remoteParentID := trace.SpanID{9, 8, 7, 6, 5, 4, 3, 2}
	remoteParent := trace.NewSpanContext(trace.SpanContextConfig{
		TraceID:    traceID,
		SpanID:     remoteParentID,
		TraceFlags: trace.FlagsSampled,
		Remote:     true,
	})

	request := httptest.NewRequest(http.MethodGet, "/api/order", nil)
	request.Header.Set(platform.RequestIDHeader, "tracing-test")
	carrier := propagation.HeaderCarrier(request.Header)
	telemetry.Propagator().Inject(trace.ContextWithRemoteSpanContext(context.Background(), remoteParent), carrier)
	response := httptest.NewRecorder()
	gatewayHandler.ServeHTTP(response, request)

	if response.Code != http.StatusOK {
		t.Fatalf("status = %d, want %d: %s", response.Code, http.StatusOK, response.Body.String())
	}
	if *ordersTraceparent == "" || *paymentTraceparent == "" {
		t.Fatalf("traceparent propagation: orders=%q payment=%q", *ordersTraceparent, *paymentTraceparent)
	}

	spans := recorder.Ended()
	if len(spans) != 5 {
		t.Fatalf("ended spans = %d, want 5", len(spans))
	}

	byName := make(map[string]sdktrace.ReadOnlySpan, len(spans))
	for _, span := range spans {
		if got := span.SpanContext().TraceID(); got != traceID {
			t.Errorf("span %q trace ID = %s, want %s", span.Name(), got, traceID)
		}
		byName[span.Name()] = span
	}

	assertParent(t, byName, "GET /api/order", remoteParentID)
	assertParent(t, byName, "GET orders", spanID(t, byName, "GET /api/order"))
	assertParent(t, byName, "GET /orders/current", spanID(t, byName, "GET orders"))
	assertParent(t, byName, "GET payment", spanID(t, byName, "GET /orders/current"))
	assertParent(t, byName, "GET /payments/authorize", spanID(t, byName, "GET payment"))

	debugResponse := httptest.NewRecorder()
	paymentHandler.ServeHTTP(debugResponse, httptest.NewRequest(http.MethodGet, "/debug/fault", nil))
	healthResponse := httptest.NewRecorder()
	paymentHandler.ServeHTTP(healthResponse, httptest.NewRequest(http.MethodGet, "/health", nil))
	if got := len(recorder.Ended()); got != 5 {
		t.Fatalf("spans after debug and health requests = %d, want 5", got)
	}
}

func instrumentedClientFor(handler http.Handler) (*http.Client, *string) {
	traceparent := new(string)
	base := roundTripperFunc(func(request *http.Request) (*http.Response, error) {
		*traceparent = request.Header.Get("traceparent")
		response := httptest.NewRecorder()
		handler.ServeHTTP(response, request)
		return response.Result(), nil
	})

	return &http.Client{Transport: telemetry.InstrumentTransport(base)}, traceparent
}

func spanID(t *testing.T, spans map[string]sdktrace.ReadOnlySpan, name string) trace.SpanID {
	t.Helper()
	span, ok := spans[name]
	if !ok {
		t.Fatalf("span %q not found", name)
	}
	return span.SpanContext().SpanID()
}

func assertParent(t *testing.T, spans map[string]sdktrace.ReadOnlySpan, name string, parent trace.SpanID) {
	t.Helper()
	span, ok := spans[name]
	if !ok {
		t.Fatalf("span %q not found", name)
	}
	if got := span.Parent().SpanID(); got != parent {
		t.Fatalf("span %q parent = %s, want %s", name, got, parent)
	}
}
