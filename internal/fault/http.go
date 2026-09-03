package fault

import (
	"context"
	"encoding/json"
	"errors"
	"io"
	"log/slog"
	"mime"
	"net/http"
	"strings"

	"go.opentelemetry.io/otel/trace"
	"vkr-rca/internal/platform"
)

const maxConfigBodyBytes = 4096

func NewHandler(injector *Injector) http.Handler {
	return http.HandlerFunc(func(writer http.ResponseWriter, request *http.Request) {
		switch request.URL.Path {
		case "/debug/fault":
			handleConfig(writer, request, injector)
		case "/debug/reset":
			handleReset(writer, request, injector)
		default:
			platform.WriteJSON(writer, http.StatusNotFound, map[string]string{"error": "not found"})
		}
	})
}

func ApplyHTTP(writer http.ResponseWriter, request *http.Request, injector *Injector, logger *slog.Logger) bool {
	outcome, err := injector.Apply(request.Context())
	if outcome.LatencyMS > 0 && !errors.Is(err, context.Canceled) && !errors.Is(err, context.DeadlineExceeded) {
		logInjected(request.Context(), logger,
			"fault_type", "latency",
			"latency_ms", outcome.LatencyMS,
		)
	}

	if errors.Is(err, ErrInjected) {
		logInjected(request.Context(), logger,
			"fault_type", "error",
			"error_rate", outcome.ErrorRate,
		)
		platform.WriteJSON(writer, http.StatusInternalServerError, map[string]string{"error": "injected fault"})
		return false
	}
	if err != nil {
		return false
	}

	return true
}

func handleConfig(writer http.ResponseWriter, request *http.Request, injector *Injector) {
	switch request.Method {
	case http.MethodGet:
		platform.WriteJSON(writer, http.StatusOK, injector.GetConfig())
	case http.MethodPost:
		if !isJSON(request.Header.Get("Content-Type")) {
			platform.WriteJSON(writer, http.StatusUnsupportedMediaType, map[string]string{"error": "Content-Type must be application/json"})
			return
		}

		config, err := decodeConfig(writer, request)
		if err != nil {
			platform.WriteJSON(writer, http.StatusBadRequest, map[string]string{"error": err.Error()})
			return
		}
		if err := injector.SetConfig(config); err != nil {
			platform.WriteJSON(writer, http.StatusBadRequest, map[string]string{"error": err.Error()})
			return
		}
		platform.WriteJSON(writer, http.StatusOK, injector.GetConfig())
	default:
		platform.MethodNotAllowed(writer, http.MethodGet+", "+http.MethodPost)
	}
}

func handleReset(writer http.ResponseWriter, request *http.Request, injector *Injector) {
	if request.Method != http.MethodPost {
		platform.MethodNotAllowed(writer, http.MethodPost)
		return
	}

	platform.WriteJSON(writer, http.StatusOK, injector.Reset())
}

func decodeConfig(writer http.ResponseWriter, request *http.Request) (Config, error) {
	request.Body = http.MaxBytesReader(writer, request.Body, maxConfigBodyBytes)
	decoder := json.NewDecoder(request.Body)
	decoder.DisallowUnknownFields()

	var config Config
	if err := decoder.Decode(&config); err != nil {
		return Config{}, errors.New("invalid fault config: " + err.Error())
	}
	if err := decoder.Decode(&struct{}{}); !errors.Is(err, io.EOF) {
		return Config{}, errors.New("invalid fault config: body must contain one JSON object")
	}
	return config, nil
}

func isJSON(contentType string) bool {
	mediaType, _, err := mime.ParseMediaType(contentType)
	return err == nil && strings.EqualFold(mediaType, "application/json")
}

func logInjected(ctx context.Context, logger *slog.Logger, attributes ...any) {
	fields := []any{
		"event", "fault_injected",
		"request_id", platform.RequestID(ctx),
	}
	if spanContext := trace.SpanContextFromContext(ctx); spanContext.IsValid() {
		fields = append(fields,
			"trace_id", spanContext.TraceID().String(),
			"span_id", spanContext.SpanID().String(),
		)
	}
	fields = append(fields, attributes...)
	logger.WarnContext(ctx, "fault injected", fields...)
}
