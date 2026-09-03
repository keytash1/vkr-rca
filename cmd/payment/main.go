package main

import (
	"context"
	"errors"
	"log/slog"
	"os"
	"os/signal"
	"syscall"
	"time"

	"vkr-rca/internal/fault"
	"vkr-rca/internal/payment"
	"vkr-rca/internal/platform"
	"vkr-rca/internal/telemetry"
)

func main() {
	logger := platform.NewLogger("payment")
	tracerShutdown, err := telemetry.InitTracerProvider(context.Background(), telemetry.Config{
		ServiceName:  "payment",
		OTLPEndpoint: platform.Env("OTEL_EXPORTER_OTLP_ENDPOINT", "localhost:4317"),
		Insecure:     platform.EnvBool("OTEL_EXPORTER_OTLP_INSECURE", true),
	})
	if err != nil {
		logger.Error("initialize tracing", slog.Any("error", err))
		os.Exit(1)
	}

	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()

	applicationHandler, err := payment.NewHandler(payment.Config{
		Logger: logger,
		Fault:  fault.New(),
	})
	if err != nil {
		logger.Error("invalid configuration", slog.Any("error", err))
		os.Exit(1)
	}
	handler := telemetry.InstrumentHandler("payment", applicationHandler)
	address := platform.Env("HTTP_ADDR", ":8082")
	serverErr := platform.Serve(ctx, address, handler, logger)

	shutdownCtx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	tracerErr := tracerShutdown(shutdownCtx)

	if err := errors.Join(serverErr, tracerErr); err != nil {
		logger.Error("service stopped with error", slog.Any("error", err))
		os.Exit(1)
	}
}
