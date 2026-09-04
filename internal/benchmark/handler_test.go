package benchmark

import (
	"io"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync/atomic"
	"testing"

	"vkr-rca/internal/fault"
)

func TestSequentialCallsEveryBranchBeforePropagatingFailure(t *testing.T) {
	var calls atomic.Int32
	client := &http.Client{Transport: roundTripFunc(func(_ *http.Request) (*http.Response, error) {
		status := http.StatusOK
		if calls.Add(1) == 1 {
			status = http.StatusInternalServerError
		}
		return response(status), nil
	})}
	handler := newTestHandler(t, CallSequential, []string{"http://first", "http://second"}, client)
	request := httptest.NewRequest(http.MethodGet, "/work", nil)
	response := httptest.NewRecorder()
	handler.ServeHTTP(response, request)
	if response.Code != http.StatusBadGateway {
		t.Fatalf("status = %d, want %d", response.Code, http.StatusBadGateway)
	}
	if calls.Load() != 2 {
		t.Fatalf("calls = %d, want 2", calls.Load())
	}
}

func TestParallelCallsAllDownstreams(t *testing.T) {
	var calls atomic.Int32
	client := &http.Client{Transport: roundTripFunc(func(_ *http.Request) (*http.Response, error) {
		calls.Add(1)
		return response(http.StatusOK), nil
	})}
	handler := newTestHandler(t, CallParallel, []string{"http://one", "http://two", "http://three"}, client)
	response := httptest.NewRecorder()
	handler.ServeHTTP(response, httptest.NewRequest(http.MethodGet, "/work", nil))
	if response.Code != http.StatusOK || calls.Load() != 3 {
		t.Fatalf("status=%d calls=%d", response.Code, calls.Load())
	}
}

func TestFaultEndpointUsesSharedInjector(t *testing.T) {
	injector := fault.New()
	if err := injector.SetConfig(fault.Config{ErrorRate: 1}); err != nil {
		t.Fatal(err)
	}
	handler, err := NewHandler(Config{
		ServiceName:    "test",
		CallMode:       CallSequential,
		ResponsePolicy: ResponsePropagate,
		Client:         http.DefaultClient,
		Logger:         slog.New(slog.NewTextHandler(io.Discard, nil)),
		Fault:          injector,
	})
	if err != nil {
		t.Fatal(err)
	}
	response := httptest.NewRecorder()
	handler.ServeHTTP(response, httptest.NewRequest(http.MethodGet, "/work", nil))
	if response.Code != http.StatusInternalServerError {
		t.Fatalf("status = %d", response.Code)
	}
}

func newTestHandler(t *testing.T, mode CallMode, downstreams []string, client *http.Client) http.Handler {
	t.Helper()
	handler, err := NewHandler(Config{
		ServiceName:    "test",
		DownstreamURLs: downstreams,
		CallMode:       mode,
		ResponsePolicy: ResponsePropagate,
		Client:         client,
		Logger:         slog.New(slog.NewTextHandler(io.Discard, nil)),
		Fault:          fault.New(),
	})
	if err != nil {
		t.Fatal(err)
	}
	return handler
}

type roundTripFunc func(*http.Request) (*http.Response, error)

func (function roundTripFunc) RoundTrip(request *http.Request) (*http.Response, error) {
	return function(request)
}

func response(status int) *http.Response {
	return &http.Response{
		StatusCode: status,
		Body:       io.NopCloser(strings.NewReader("{}")),
		Header:     make(http.Header),
	}
}
