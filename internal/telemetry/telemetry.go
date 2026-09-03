package telemetry

import (
	"context"
	"errors"
	"fmt"
	"net/http"
	"strings"
	"time"

	"go.opentelemetry.io/contrib/instrumentation/net/http/otelhttp"
	"go.opentelemetry.io/otel"
	"go.opentelemetry.io/otel/attribute"
	"go.opentelemetry.io/otel/exporters/otlp/otlptrace/otlptracegrpc"
	"go.opentelemetry.io/otel/propagation"
	"go.opentelemetry.io/otel/sdk/resource"
	sdktrace "go.opentelemetry.io/otel/sdk/trace"
)

const batchTimeout = time.Second

type Config struct {
	ServiceName  string
	OTLPEndpoint string
	Insecure     bool
}

func InitTracerProvider(ctx context.Context, config Config) (func(context.Context) error, error) {
	if strings.TrimSpace(config.ServiceName) == "" {
		return nil, errors.New("service name is required")
	}
	if strings.TrimSpace(config.OTLPEndpoint) == "" {
		return nil, errors.New("OTLP endpoint is required")
	}

	exporterOptions := []otlptracegrpc.Option{
		otlptracegrpc.WithEndpoint(config.OTLPEndpoint),
	}
	if config.Insecure {
		exporterOptions = append(exporterOptions, otlptracegrpc.WithInsecure())
	}

	exporter, err := otlptracegrpc.New(ctx, exporterOptions...)
	if err != nil {
		return nil, fmt.Errorf("create OTLP trace exporter: %w", err)
	}

	serviceResource, err := resource.Merge(
		resource.Default(),
		resource.NewSchemaless(attribute.String("service.name", config.ServiceName)),
	)
	if err != nil {
		return nil, fmt.Errorf("create telemetry resource: %w", err)
	}

	provider := sdktrace.NewTracerProvider(
		sdktrace.WithResource(serviceResource),
		sdktrace.WithSampler(sdktrace.ParentBased(sdktrace.AlwaysSample())),
		sdktrace.WithBatcher(exporter, sdktrace.WithBatchTimeout(batchTimeout)),
	)

	otel.SetTracerProvider(provider)
	otel.SetTextMapPropagator(Propagator())

	return provider.Shutdown, nil
}

func Propagator() propagation.TextMapPropagator {
	return propagation.NewCompositeTextMapPropagator(
		propagation.TraceContext{},
		propagation.Baggage{},
	)
}

func InstrumentHandler(serviceName string, handler http.Handler) http.Handler {
	return otelhttp.NewHandler(
		handler,
		serviceName,
		otelhttp.WithFilter(func(request *http.Request) bool {
			return request.URL.Path != "/health"
		}),
		otelhttp.WithSpanNameFormatter(func(_ string, request *http.Request) string {
			return request.Method + " " + request.URL.Path
		}),
	)
}

func InstrumentTransport(base http.RoundTripper) http.RoundTripper {
	if base == nil {
		base = http.DefaultTransport
	}

	return otelhttp.NewTransport(
		base,
		otelhttp.WithSpanNameFormatter(func(_ string, request *http.Request) string {
			return request.Method + " " + request.URL.Host
		}),
	)
}

func NewHTTPClient(timeout time.Duration) *http.Client {
	return &http.Client{
		Transport: InstrumentTransport(http.DefaultTransport),
		Timeout:   timeout,
	}
}
