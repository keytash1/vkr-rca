package payment

import (
	"errors"
	"log/slog"
	"net/http"

	"vkr-rca/internal/fault"
	"vkr-rca/internal/platform"
)

type Config struct {
	Logger *slog.Logger
	Fault  *fault.Injector
}

type handler struct {
	logger *slog.Logger
	fault  *fault.Injector
}

func NewHandler(config Config) (http.Handler, error) {
	if config.Logger == nil {
		return nil, errors.New("logger is required")
	}
	if config.Fault == nil {
		return nil, errors.New("fault injector is required")
	}

	handler := &handler{logger: config.Logger, fault: config.Fault}
	mux := http.NewServeMux()
	mux.HandleFunc("/health", platform.HealthHandler("payment"))
	mux.HandleFunc("/payments/authorize", handler.authorize)
	mux.Handle("/debug/", fault.NewHandler(config.Fault))
	return platform.Middleware(config.Logger, mux), nil
}

func (handler *handler) authorize(writer http.ResponseWriter, request *http.Request) {
	if request.Method != http.MethodGet {
		platform.MethodNotAllowed(writer, http.MethodGet)
		return
	}
	if !fault.ApplyHTTP(writer, request, handler.fault, handler.logger) {
		return
	}

	platform.WriteJSON(writer, http.StatusOK, map[string]string{
		"provider": "payment",
		"status":   "authorized",
	})
}
