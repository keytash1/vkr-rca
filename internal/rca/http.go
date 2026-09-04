package rca

import (
	"errors"
	"log/slog"
	"net/http"
	"strings"

	"vkr-rca/internal/anomaly"
	"vkr-rca/internal/graph"
	"vkr-rca/internal/platform"
)

func NewHTTPHandler(
	store *graph.Store,
	logger *slog.Logger,
	detector *anomaly.Detector,
	diagnosisProvider *DiagnosisProvider,
) http.Handler {
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
	if detector != nil {
		mountAnomalyHandlers(mux, detector)
	}
	if diagnosisProvider != nil {
		mountDiagnosisHandlers(mux, diagnosisProvider)
	}

	return platform.Middleware(logger, mux)
}

func mountDiagnosisHandlers(mux *http.ServeMux, provider *DiagnosisProvider) {
	mux.HandleFunc("/api/features", func(writer http.ResponseWriter, request *http.Request) {
		if request.Method != http.MethodGet {
			platform.MethodNotAllowed(writer, http.MethodGet)
			return
		}
		platform.WriteJSON(writer, http.StatusOK, provider.Features())
	})
	mux.HandleFunc("/api/rca", func(writer http.ResponseWriter, request *http.Request) {
		if request.Method != http.MethodGet {
			platform.MethodNotAllowed(writer, http.MethodGet)
			return
		}
		platform.WriteJSON(writer, http.StatusOK, provider.RCA())
	})
}

func mountAnomalyHandlers(mux *http.ServeMux, detector *anomaly.Detector) {
	mux.HandleFunc("/api/baseline", func(writer http.ResponseWriter, request *http.Request) {
		if request.Method != http.MethodGet {
			platform.MethodNotAllowed(writer, http.MethodGet)
			return
		}
		platform.WriteJSON(writer, http.StatusOK, detector.Baseline())
	})
	mux.HandleFunc("/api/anomalies", func(writer http.ResponseWriter, request *http.Request) {
		if request.Method != http.MethodGet {
			platform.MethodNotAllowed(writer, http.MethodGet)
			return
		}
		platform.WriteJSON(writer, http.StatusOK, detector.Anomalies())
	})
	mux.HandleFunc("/debug/baseline/start", func(writer http.ResponseWriter, request *http.Request) {
		if request.Method != http.MethodPost {
			platform.MethodNotAllowed(writer, http.MethodPost)
			return
		}
		detector.StartBaseline()
		platform.WriteJSON(writer, http.StatusOK, detector.Baseline())
	})
	mux.HandleFunc("/debug/baseline/freeze", func(writer http.ResponseWriter, request *http.Request) {
		if request.Method != http.MethodPost {
			platform.MethodNotAllowed(writer, http.MethodPost)
			return
		}
		if err := detector.FreezeBaseline(); err != nil {
			if errors.Is(err, anomaly.ErrBaselineNotCollecting) {
				platform.WriteJSON(writer, http.StatusConflict, map[string]string{"error": err.Error()})
				return
			}
			platform.WriteJSON(writer, http.StatusInternalServerError, map[string]string{"error": err.Error()})
			return
		}
		platform.WriteJSON(writer, http.StatusOK, detector.Baseline())
	})
	mux.HandleFunc("/debug/anomaly/reset", func(writer http.ResponseWriter, request *http.Request) {
		if request.Method != http.MethodPost {
			platform.MethodNotAllowed(writer, http.MethodPost)
			return
		}
		detector.ResetCurrent()
		platform.WriteJSON(writer, http.StatusOK, detector.Anomalies())
	})
}
