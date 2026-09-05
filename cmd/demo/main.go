package main

import (
	"context"
	"embed"
	"io/fs"
	"log/slog"
	"os"
	"os/signal"
	"syscall"
	"time"

	"vkr-rca/internal/demo"
	"vkr-rca/internal/platform"
)

//go:embed static/*
var staticFiles embed.FS

func main() {
	logger := platform.NewLogger("demo")
	root := platform.Env("DEMO_ROOT", ".")
	operationTimeout := platform.EnvDuration("DEMO_OPERATION_TIMEOUT", 60*time.Second)
	server, err := demo.NewServer(demo.Config{
		Root:             root,
		OperationTimeout: operationTimeout,
		Live: demo.LiveConfig{
			GatewayURL:       platform.Env("GATEWAY_URL", "http://127.0.0.1:18080"),
			OrdersURL:        platform.Env("ORDERS_URL", "http://127.0.0.1:8081"),
			PaymentURL:       platform.Env("PAYMENT_URL", "http://127.0.0.1:8082"),
			RCAURL:           platform.Env("RCA_URL", "http://127.0.0.1:18090"),
			RequestTimeout:   platform.EnvDuration("DEMO_REQUEST_TIMEOUT", 5*time.Second),
			DrainDuration:    platform.EnvDuration("DEMO_COLLECTOR_DRAIN", 3*time.Second),
			BaselineRequests: platform.EnvInt("DEMO_BASELINE_REQUESTS", 50),
		},
	})
	if err != nil {
		logger.Error("initialize demo", slog.Any("error", err))
		os.Exit(1)
	}
	static, err := fs.Sub(staticFiles, "static")
	if err != nil {
		logger.Error("load embedded frontend", slog.Any("error", err))
		os.Exit(1)
	}

	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()
	address := platform.Env("DEMO_ADDR", "127.0.0.1:18000")
	if err := platform.ServeWithWriteTimeout(ctx, address, server.Handler(static), logger, operationTimeout+10*time.Second); err != nil {
		logger.Error("demo server stopped", slog.Any("error", err))
		os.Exit(1)
	}
}
