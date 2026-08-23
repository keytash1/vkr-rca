package payment

import (
	"encoding/json"
	"io"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"testing"
)

func TestAuthorize(t *testing.T) {
	request := httptest.NewRequest(http.MethodGet, "/payments/authorize", nil)
	response := httptest.NewRecorder()

	NewHandler(testLogger()).ServeHTTP(response, request)

	if response.Code != http.StatusOK {
		t.Fatalf("status = %d, want %d", response.Code, http.StatusOK)
	}

	var body map[string]string
	if err := json.NewDecoder(response.Body).Decode(&body); err != nil {
		t.Fatalf("decode response: %v", err)
	}
	if body["status"] != "authorized" {
		t.Fatalf("payment status = %q, want authorized", body["status"])
	}
}

func TestAuthorizeRejectsUnsupportedMethod(t *testing.T) {
	request := httptest.NewRequest(http.MethodPost, "/payments/authorize", nil)
	response := httptest.NewRecorder()

	NewHandler(testLogger()).ServeHTTP(response, request)

	if response.Code != http.StatusMethodNotAllowed {
		t.Fatalf("status = %d, want %d", response.Code, http.StatusMethodNotAllowed)
	}
}

func testLogger() *slog.Logger {
	return slog.New(slog.NewTextHandler(io.Discard, nil))
}
