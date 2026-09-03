package main

import (
	"context"
	"errors"
	"log/slog"
	"os"
	"os/signal"
	"syscall"
	"time"

	"vkr-rca/internal/gateway"
	"vkr-rca/internal/platform"
	"vkr-rca/internal/telemetry"
)

func main() {
	logger := platform.NewLogger("gateway")
	tracerShutdown, err := telemetry.InitTracerProvider(context.Background(), telemetry.Config{
		ServiceName:  "gateway",
		OTLPEndpoint: platform.Env("OTEL_EXPORTER_OTLP_ENDPOINT", "localhost:4317"),
		Insecure:     platform.EnvBool("OTEL_EXPORTER_OTLP_INSECURE", true),
	})
	if err != nil {
		logger.Error("initialize tracing", slog.Any("error", err))
		os.Exit(1)
	}

	clientTimeout := platform.EnvDuration("HTTP_CLIENT_TIMEOUT", 3*time.Second)
	applicationHandler, err := gateway.NewHandler(gateway.Config{
		OrdersURL: platform.Env("ORDERS_URL", "http://orders:8081"),
		Client:    telemetry.NewHTTPClient(clientTimeout),
		Logger:    logger,
	})
	if err != nil {
		logger.Error("invalid configuration", slog.Any("error", err))
		os.Exit(1)
	}

	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()

	handler := telemetry.InstrumentHandler("gateway", applicationHandler)
	address := platform.Env("HTTP_ADDR", ":8080")
	serverErr := platform.Serve(ctx, address, handler, logger)

	shutdownCtx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	tracerErr := tracerShutdown(shutdownCtx)

	if err := errors.Join(serverErr, tracerErr); err != nil {
		logger.Error("service stopped with error", slog.Any("error", err))
		os.Exit(1)
	}
}
