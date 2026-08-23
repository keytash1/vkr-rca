package main

import (
	"context"
	"log/slog"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"vkr-rca/internal/gateway"
	"vkr-rca/internal/platform"
)

func main() {
	logger := platform.NewLogger("gateway")
	clientTimeout := platform.EnvDuration("HTTP_CLIENT_TIMEOUT", 3*time.Second)
	handler, err := gateway.NewHandler(gateway.Config{
		OrdersURL: platform.Env("ORDERS_URL", "http://orders:8081"),
		Client:    &http.Client{Timeout: clientTimeout},
		Logger:    logger,
	})
	if err != nil {
		logger.Error("invalid configuration", slog.Any("error", err))
		os.Exit(1)
	}

	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()

	address := platform.Env("HTTP_ADDR", ":8080")
	if err := platform.Serve(ctx, address, handler, logger); err != nil {
		logger.Error("server failed", slog.Any("error", err))
		os.Exit(1)
	}
}
