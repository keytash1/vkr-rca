package main

import (
	"context"
	"errors"
	"log/slog"
	"net"
	"os"
	"os/signal"
	"syscall"
	"time"

	collecttracev1 "go.opentelemetry.io/proto/otlp/collector/trace/v1"
	"google.golang.org/grpc"
	"vkr-rca/internal/anomaly"
	"vkr-rca/internal/graph"
	"vkr-rca/internal/platform"
	"vkr-rca/internal/rca"
)

const shutdownTimeout = 10 * time.Second

func main() {
	logger := platform.NewLogger("rca")
	store, err := graph.NewStore(graph.Config{
		TraceTTL:  platform.EnvDuration("TRACE_TTL", graph.DefaultTraceTTL),
		MaxTraces: platform.EnvInt("MAX_TRACES", graph.DefaultMaxTraces),
	})
	if err != nil {
		logger.Error("invalid graph configuration", slog.Any("error", err))
		os.Exit(1)
	}
	detector, err := anomaly.NewDetector(anomaly.Config{
		MinBaselineSamples: platform.EnvInt("MIN_BASELINE_SAMPLES", anomaly.DefaultMinBaselineSamples),
		MaxBaselineSamples: platform.EnvInt("MAX_BASELINE_SAMPLES", anomaly.DefaultMaxBaselineSamples),
		CurrentWindowSize:  platform.EnvInt("CURRENT_WINDOW_SIZE", anomaly.DefaultCurrentWindowSize),
		MinCurrentSamples:  platform.EnvInt("MIN_CURRENT_SAMPLES", anomaly.DefaultMinCurrentSamples),
		LatencyZThreshold:  platform.EnvFloat64("LATENCY_Z_THRESHOLD", anomaly.DefaultLatencyZThreshold),
		ErrorZThreshold:    platform.EnvFloat64("ERROR_Z_THRESHOLD", anomaly.DefaultErrorZThreshold),
		ScaleEpsilon:       platform.EnvFloat64("ROBUST_SCALE_EPSILON", anomaly.DefaultScaleEpsilon),
	})
	if err != nil {
		logger.Error("invalid anomaly detector configuration", slog.Any("error", err))
		os.Exit(1)
	}

	otlpAddress := platform.Env("OTLP_ADDR", ":4317")
	listener, err := net.Listen("tcp", otlpAddress)
	if err != nil {
		logger.Error("listen for OTLP", slog.Any("error", err))
		os.Exit(1)
	}

	grpcServer := grpc.NewServer()
	collecttracev1.RegisterTraceServiceServer(
		grpcServer,
		rca.NewReceiver(store, logger, rca.NewAnomalyObserver(detector)),
	)

	signalCtx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()
	runCtx, cancel := context.WithCancel(signalCtx)
	defer cancel()

	grpcErrors := make(chan error, 1)
	go func() {
		logger.Info("OTLP receiver started", "address", otlpAddress)
		grpcErrors <- grpcServer.Serve(listener)
		cancel()
	}()

	httpAddress := platform.Env("HTTP_ADDR", ":8090")
	httpErr := platform.Serve(runCtx, httpAddress, rca.NewHTTPHandler(store, logger, detector), logger)
	cancel()
	stopGRPC(grpcServer)

	grpcErr := <-grpcErrors
	if errors.Is(grpcErr, grpc.ErrServerStopped) {
		grpcErr = nil
	}
	if err := errors.Join(httpErr, grpcErr); err != nil {
		logger.Error("service stopped with error", slog.Any("error", err))
		os.Exit(1)
	}
}

func stopGRPC(server *grpc.Server) {
	stopped := make(chan struct{})
	go func() {
		server.GracefulStop()
		close(stopped)
	}()

	timer := time.NewTimer(shutdownTimeout)
	defer timer.Stop()
	select {
	case <-stopped:
	case <-timer.C:
		server.Stop()
		<-stopped
	}
}
