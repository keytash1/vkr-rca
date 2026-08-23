package payment

import (
	"log/slog"
	"net/http"

	"vkr-rca/internal/platform"
)

func NewHandler(logger *slog.Logger) http.Handler {
	mux := http.NewServeMux()
	mux.HandleFunc("/health", platform.HealthHandler("payment"))
	mux.HandleFunc("/payments/authorize", authorize)
	return platform.Middleware(logger, mux)
}

func authorize(writer http.ResponseWriter, request *http.Request) {
	if request.Method != http.MethodGet {
		platform.MethodNotAllowed(writer, http.MethodGet)
		return
	}

	platform.WriteJSON(writer, http.StatusOK, map[string]string{
		"provider": "payment",
		"status":   "authorized",
	})
}
