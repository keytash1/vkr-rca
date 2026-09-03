package integration_test

import (
	"context"
	"io"
	"log/slog"
	"net"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"

	"go.opentelemetry.io/contrib/instrumentation/net/http/otelhttp"
	"go.opentelemetry.io/otel/attribute"
	"go.opentelemetry.io/otel/exporters/otlp/otlptrace/otlptracegrpc"
	"go.opentelemetry.io/otel/sdk/resource"
	sdktrace "go.opentelemetry.io/otel/sdk/trace"
	collecttracev1 "go.opentelemetry.io/proto/otlp/collector/trace/v1"
	"google.golang.org/grpc"
	"google.golang.org/grpc/credentials/insecure"
	"google.golang.org/grpc/test/bufconn"
	"vkr-rca/internal/fault"
	"vkr-rca/internal/gateway"
	"vkr-rca/internal/graph"
	"vkr-rca/internal/orders"
	"vkr-rca/internal/payment"
	"vkr-rca/internal/rca"
	"vkr-rca/internal/telemetry"
)

func TestRealInstrumentedChainBuildsServiceGraphThroughOTLP(t *testing.T) {
	ctx := context.Background()
	store, err := graph.NewStore(graph.Config{TraceTTL: graph.DefaultTraceTTL, MaxTraces: graph.DefaultMaxTraces})
	if err != nil {
		t.Fatalf("new graph store: %v", err)
	}

	listener := bufconn.Listen(1 << 20)
	grpcServer := grpc.NewServer()
	collecttracev1.RegisterTraceServiceServer(grpcServer, rca.NewReceiver(store, slog.New(slog.NewTextHandler(io.Discard, nil))))
	go func() { _ = grpcServer.Serve(listener) }()
	t.Cleanup(grpcServer.Stop)

	connection, err := grpc.NewClient(
		"passthrough:///rca-test",
		grpc.WithContextDialer(func(context.Context, string) (net.Conn, error) { return listener.Dial() }),
		grpc.WithTransportCredentials(insecure.NewCredentials()),
	)
	if err != nil {
		t.Fatalf("connect OTLP receiver: %v", err)
	}
	t.Cleanup(func() { _ = connection.Close() })

	gatewayProvider := graphTracerProvider(t, ctx, connection, "gateway")
	ordersProvider := graphTracerProvider(t, ctx, connection, "orders")
	paymentProvider := graphTracerProvider(t, ctx, connection, "payment")
	logger := slog.New(slog.NewTextHandler(io.Discard, nil))

	paymentApplication, err := payment.NewHandler(payment.Config{Logger: logger, Fault: fault.New()})
	if err != nil {
		t.Fatalf("create Payment handler: %v", err)
	}
	paymentHandler := graphServerHandler(paymentApplication, paymentProvider)
	paymentClient := graphHTTPClient(paymentHandler, ordersProvider)

	ordersApplication, err := orders.NewHandler(orders.Config{
		PaymentURL: "http://payment",
		Client:     paymentClient,
		Logger:     logger,
		Fault:      fault.New(),
	})
	if err != nil {
		t.Fatalf("create Orders handler: %v", err)
	}
	ordersHandler := graphServerHandler(ordersApplication, ordersProvider)
	ordersClient := graphHTTPClient(ordersHandler, gatewayProvider)

	gatewayApplication, err := gateway.NewHandler(gateway.Config{
		OrdersURL: "http://orders",
		Client:    ordersClient,
		Logger:    logger,
	})
	if err != nil {
		t.Fatalf("create Gateway handler: %v", err)
	}
	gatewayHandler := graphServerHandler(gatewayApplication, gatewayProvider)

	response := httptest.NewRecorder()
	gatewayHandler.ServeHTTP(response, httptest.NewRequest(http.MethodGet, "/api/order", nil))
	if response.Code != http.StatusOK {
		t.Fatalf("Gateway status = %d: %s", response.Code, response.Body.String())
	}
	for _, provider := range []*sdktrace.TracerProvider{gatewayProvider, ordersProvider, paymentProvider} {
		if err := provider.ForceFlush(ctx); err != nil {
			t.Fatalf("flush spans: %v", err)
		}
	}

	snapshot := store.Snapshot()
	if len(snapshot.Nodes) != 3 || len(snapshot.Edges) != 2 {
		t.Fatalf("graph = %+v", snapshot)
	}
	if snapshot.Edges[0].Source != "gateway" || snapshot.Edges[0].Target != "orders" ||
		snapshot.Edges[1].Source != "orders" || snapshot.Edges[1].Target != "payment" {
		t.Fatalf("topology = %+v", snapshot.Edges)
	}
}

func graphTracerProvider(t *testing.T, ctx context.Context, connection *grpc.ClientConn, service string) *sdktrace.TracerProvider {
	t.Helper()
	exporter, err := otlptracegrpc.New(ctx,
		otlptracegrpc.WithGRPCConn(connection),
		otlptracegrpc.WithCompressor("gzip"),
	)
	if err != nil {
		t.Fatalf("create %s exporter: %v", service, err)
	}
	serviceResource := resource.NewSchemaless(attribute.String("service.name", service))
	provider := sdktrace.NewTracerProvider(
		sdktrace.WithResource(serviceResource),
		sdktrace.WithSampler(sdktrace.AlwaysSample()),
		sdktrace.WithSyncer(exporter),
	)
	t.Cleanup(func() {
		shutdownCtx, cancel := context.WithTimeout(context.Background(), time.Second)
		defer cancel()
		_ = provider.Shutdown(shutdownCtx)
	})
	return provider
}

func graphServerHandler(handler http.Handler, provider *sdktrace.TracerProvider) http.Handler {
	return otelhttp.NewHandler(
		handler,
		"server",
		otelhttp.WithTracerProvider(provider),
		otelhttp.WithPropagators(telemetry.Propagator()),
		otelhttp.WithSpanNameFormatter(func(_ string, request *http.Request) string {
			return request.Method + " " + request.URL.Path
		}),
	)
}

func graphHTTPClient(handler http.Handler, provider *sdktrace.TracerProvider) *http.Client {
	transport := roundTripperFunc(func(request *http.Request) (*http.Response, error) {
		response := httptest.NewRecorder()
		handler.ServeHTTP(response, request)
		return response.Result(), nil
	})
	return &http.Client{Transport: otelhttp.NewTransport(
		transport,
		otelhttp.WithTracerProvider(provider),
		otelhttp.WithPropagators(telemetry.Propagator()),
	)}
}
