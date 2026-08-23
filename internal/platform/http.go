package platform

import (
	"context"
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"log/slog"
	"net/http"
	"time"
)

const RequestIDHeader = "X-Request-ID"

type requestIDKey struct{}

func RequestID(ctx context.Context) string {
	requestID, _ := ctx.Value(requestIDKey{}).(string)
	return requestID
}

func NewRequest(ctx context.Context, method, url string) (*http.Request, error) {
	request, err := http.NewRequestWithContext(ctx, method, url, nil)
	if err != nil {
		return nil, err
	}

	if requestID := RequestID(ctx); requestID != "" {
		request.Header.Set(RequestIDHeader, requestID)
	}

	return request, nil
}

func Middleware(logger *slog.Logger, next http.Handler) http.Handler {
	return http.HandlerFunc(func(writer http.ResponseWriter, request *http.Request) {
		startedAt := time.Now()
		requestID := request.Header.Get(RequestIDHeader)
		if requestID == "" {
			requestID = newRequestID()
		}

		writer.Header().Set(RequestIDHeader, requestID)
		response := &responseWriter{ResponseWriter: writer, status: http.StatusOK}
		ctx := context.WithValue(request.Context(), requestIDKey{}, requestID)
		next.ServeHTTP(response, request.WithContext(ctx))

		logger.InfoContext(ctx, "request completed",
			"request_id", requestID,
			"method", request.Method,
			"path", request.URL.Path,
			"status", response.status,
			"duration_ms", time.Since(startedAt).Milliseconds(),
		)
	})
}

func WriteJSON(writer http.ResponseWriter, status int, value any) {
	writer.Header().Set("Content-Type", "application/json")
	writer.WriteHeader(status)
	_ = json.NewEncoder(writer).Encode(value)
}

func MethodNotAllowed(writer http.ResponseWriter, allowed string) {
	writer.Header().Set("Allow", allowed)
	WriteJSON(writer, http.StatusMethodNotAllowed, map[string]string{"error": "method not allowed"})
}

func HealthHandler(service string) http.HandlerFunc {
	return func(writer http.ResponseWriter, request *http.Request) {
		if request.Method != http.MethodGet {
			MethodNotAllowed(writer, http.MethodGet)
			return
		}

		WriteJSON(writer, http.StatusOK, map[string]string{
			"service": service,
			"status":  "ok",
		})
	}
}

func newRequestID() string {
	bytes := make([]byte, 16)
	if _, err := rand.Read(bytes); err != nil {
		return time.Now().UTC().Format("20060102150405.000000000")
	}

	return hex.EncodeToString(bytes)
}

type responseWriter struct {
	http.ResponseWriter
	status      int
	wroteHeader bool
}

func (writer *responseWriter) WriteHeader(status int) {
	if writer.wroteHeader {
		return
	}
	writer.wroteHeader = true
	writer.status = status
	writer.ResponseWriter.WriteHeader(status)
}
