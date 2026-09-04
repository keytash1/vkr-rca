package main

import (
	"context"
	"errors"
	"log/slog"
	"os"
	"os/signal"
	"syscall"
	"time"

	"vkr-rca/internal/benchmark"
	"vkr-rca/internal/fault"
	"vkr-rca/internal/platform"
	"vkr-rca/internal/telemetry"
)

func main() {
	serviceName := platform.Env("SERVICE_NAME", "benchmark")
	logger := platform.NewLogger(serviceName)
	tracerShutdown, err := telemetry.InitTracerProvider(context.Background(), telemetry.Config{
		ServiceName:  serviceName,
		OTLPEndpoint: platform.Env("OTEL_EXPORTER_OTLP_ENDPOINT", "localhost:4317"),
		Insecure:     platform.EnvBool("OTEL_EXPORTER_OTLP_INSECURE", true),
	})
	if err != nil {
		logger.Error("initialize tracing", slog.Any("error", err))
		os.Exit(1)
	}

	applicationHandler, err := benchmark.NewHandler(benchmark.Config{
		ServiceName:    serviceName,
		DownstreamURLs: benchmark.ParseDownstreamURLs(platform.Env("DOWNSTREAM_URLS", "")),
		CallMode:       benchmark.CallMode(platform.Env("CALL_MODE", string(benchmark.CallSequential))),
		ResponsePolicy: benchmark.ResponsePolicy(platform.Env("RESPONSE_POLICY", string(benchmark.ResponsePropagate))),
		Client:         telemetry.NewHTTPClient(platform.EnvDuration("HTTP_CLIENT_TIMEOUT", 5*time.Second)),
		Logger:         logger,
		Fault:          fault.New(),
	})
	if err != nil {
		logger.Error("invalid configuration", slog.Any("error", err))
		os.Exit(1)
	}

	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()
	serverErr := platform.Serve(
		ctx,
		platform.Env("HTTP_ADDR", ":8080"),
		telemetry.InstrumentHandler(serviceName, applicationHandler),
		logger,
	)

	shutdownCtx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	if err := errors.Join(serverErr, tracerShutdown(shutdownCtx)); err != nil {
		logger.Error("service stopped with error", slog.Any("error", err))
		os.Exit(1)
	}
}
