package main

import (
	"context"
	"log/slog"
	"os"
	"os/signal"
	"syscall"

	"vkr-rca/internal/payment"
	"vkr-rca/internal/platform"
)

func main() {
	logger := platform.NewLogger("payment")
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()

	handler := payment.NewHandler(logger)
	address := platform.Env("HTTP_ADDR", ":8082")
	if err := platform.Serve(ctx, address, handler, logger); err != nil {
		logger.Error("server failed", slog.Any("error", err))
		os.Exit(1)
	}
}
