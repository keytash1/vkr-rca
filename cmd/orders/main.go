package main

import (
	"context"
	"log/slog"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"vkr-rca/internal/orders"
	"vkr-rca/internal/platform"
)

func main() {
	logger := platform.NewLogger("orders")
	clientTimeout := platform.EnvDuration("HTTP_CLIENT_TIMEOUT", 2*time.Second)
	handler, err := orders.NewHandler(orders.Config{
		PaymentURL: platform.Env("PAYMENT_URL", "http://payment:8082"),
		Client:     &http.Client{Timeout: clientTimeout},
		Logger:     logger,
	})
	if err != nil {
		logger.Error("invalid configuration", slog.Any("error", err))
		os.Exit(1)
	}

	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()

	address := platform.Env("HTTP_ADDR", ":8081")
	if err := platform.Serve(ctx, address, handler, logger); err != nil {
		logger.Error("server failed", slog.Any("error", err))
		os.Exit(1)
	}
}
