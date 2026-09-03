package rca

import (
	"log/slog"
	"net/http"
	"strings"

	"vkr-rca/internal/graph"
	"vkr-rca/internal/platform"
)

func NewHTTPHandler(store *graph.Store, logger *slog.Logger) http.Handler {
	mux := http.NewServeMux()
	mux.HandleFunc("/health", platform.HealthHandler("rca"))
	mux.HandleFunc("/api/graph", func(writer http.ResponseWriter, request *http.Request) {
		if request.Method != http.MethodGet {
			platform.MethodNotAllowed(writer, http.MethodGet)
			return
		}
		platform.WriteJSON(writer, http.StatusOK, store.Snapshot())
	})
	mux.HandleFunc("/api/traces/", func(writer http.ResponseWriter, request *http.Request) {
		if request.Method != http.MethodGet {
			platform.MethodNotAllowed(writer, http.MethodGet)
			return
		}
		traceID := strings.TrimPrefix(request.URL.Path, "/api/traces/")
		if traceID == "" || strings.Contains(traceID, "/") {
			platform.WriteJSON(writer, http.StatusNotFound, map[string]string{"error": "trace not found"})
			return
		}
		spans, found := store.Trace(traceID)
		if !found {
			platform.WriteJSON(writer, http.StatusNotFound, map[string]string{"error": "trace not found"})
			return
		}
		platform.WriteJSON(writer, http.StatusOK, map[string]any{
			"trace_id": traceID,
			"spans":    spans,
		})
	})
	mux.HandleFunc("/debug/reset", func(writer http.ResponseWriter, request *http.Request) {
		if request.Method != http.MethodPost {
			platform.MethodNotAllowed(writer, http.MethodPost)
			return
		}
		store.Reset()
		platform.WriteJSON(writer, http.StatusOK, store.Snapshot())
	})

	return platform.Middleware(logger, mux)
}
