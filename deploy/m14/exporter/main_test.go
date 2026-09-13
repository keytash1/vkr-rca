package main

import (
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"
)

type roundTripFunc func(*http.Request) (*http.Response, error)

func (f roundTripFunc) RoundTrip(request *http.Request) (*http.Response, error) {
	return f(request)
}

func TestFailedContainerDoesNotFreezeOtherSamples(t *testing.T) {
	client := &http.Client{Transport: roundTripFunc(func(request *http.Request) (*http.Response, error) {
		status, body := http.StatusOK, "{}"
		switch request.URL.Path {
		case "/v1.44/containers/json":
			body = `[{"Id":"good","Labels":{"io.vkr.m14.role":"application","com.docker.compose.service":"good"}},{"Id":"bad","Labels":{"io.vkr.m14.role":"application","com.docker.compose.service":"bad"}}]`
		case "/v1.44/containers/bad/stats":
			status = http.StatusInternalServerError
		}
		return &http.Response{StatusCode: status, Body: io.NopCloser(strings.NewReader(body))}, nil
	})}
	state.Lock()
	state.samples = []sample{{service: "stale"}}
	state.Unlock()
	if err := collect(client); err == nil {
		t.Fatal("failed container was not reported")
	}
	state.RLock()
	defer state.RUnlock()
	if len(state.samples) != 1 || state.samples[0].service != "good" {
		t.Fatalf("snapshot did not replace stale samples: %+v", state.samples)
	}
}

func TestMetricsDoesNotReplayStaleSamples(t *testing.T) {
	state.Lock()
	state.samples = []sample{{service: "example", cpu: 1}}
	state.updatedAt = time.Now().Add(-11 * time.Second)
	state.Unlock()
	response := httptest.NewRecorder()
	metrics(response, httptest.NewRequest(http.MethodGet, "/metrics", nil))
	if response.Code != http.StatusServiceUnavailable || strings.Contains(response.Body.String(), "cpu_cores") {
		t.Fatalf("stale metrics were exposed: %d %s", response.Code, response.Body.String())
	}
	state.Lock()
	state.updatedAt = time.Now()
	state.Unlock()
	response = httptest.NewRecorder()
	metrics(response, httptest.NewRequest(http.MethodGet, "/metrics", nil))
	if response.Code != http.StatusOK || !strings.Contains(response.Body.String(), "cpu_cores") {
		t.Fatalf("fresh metrics were not exposed: %d %s", response.Code, response.Body.String())
	}
}
