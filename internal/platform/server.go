package platform

import (
	"context"
	"errors"
	"log/slog"
	"net/http"
	"os"
	"time"
)

const shutdownTimeout = 10 * time.Second

func NewLogger(service string) *slog.Logger {
	return slog.New(slog.NewJSONHandler(os.Stdout, nil)).With("service", service)
}

func Serve(ctx context.Context, address string, handler http.Handler, logger *slog.Logger) error {
	return serve(ctx, address, handler, logger, 5*time.Second)
}

func ServeWithWriteTimeout(ctx context.Context, address string, handler http.Handler, logger *slog.Logger, writeTimeout time.Duration) error {
	if writeTimeout <= 0 {
		return errors.New("write timeout must be positive")
	}
	return serve(ctx, address, handler, logger, writeTimeout)
}

func serve(ctx context.Context, address string, handler http.Handler, logger *slog.Logger, writeTimeout time.Duration) error {
	server := &http.Server{
		Addr:              address,
		Handler:           handler,
		ReadHeaderTimeout: 2 * time.Second,
		ReadTimeout:       5 * time.Second,
		WriteTimeout:      writeTimeout,
		IdleTimeout:       30 * time.Second,
	}

	serveErrors := make(chan error, 1)
	go func() {
		logger.Info("server started", "address", address)
		serveErrors <- server.ListenAndServe()
	}()

	select {
	case err := <-serveErrors:
		if errors.Is(err, http.ErrServerClosed) {
			return nil
		}
		return err
	case <-ctx.Done():
	}

	shutdownCtx, cancel := context.WithTimeout(context.Background(), shutdownTimeout)
	defer cancel()

	logger.Info("server stopping")
	if err := server.Shutdown(shutdownCtx); err != nil {
		return err
	}

	err := <-serveErrors
	if errors.Is(err, http.ErrServerClosed) {
		return nil
	}
	return err
}
