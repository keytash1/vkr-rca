package telemetry

import (
	"fmt"
	"io"
	"net/http"
	"net/http/httptest"
	"strconv"
	"strings"
	"sync"
	"testing"
)

func redSample(t *testing.T, text, name string, labels ...string) float64 {
	t.Helper()
	for _, line := range strings.Split(text, "\n") {
		if !strings.HasPrefix(line, name+"{") {
			continue
		}
		matches := true
		for _, label := range labels {
			matches = matches && strings.Contains(line, label)
		}
		if matches {
			parts := strings.Fields(line)
			value, err := strconv.ParseFloat(parts[len(parts)-1], 64)
			if err != nil {
				t.Fatal(err)
			}
			return value
		}
	}
	t.Fatalf("missing metric %s %v", name, labels)
	return 0
}

func redScrape(t *testing.T, handler http.Handler) string {
	t.Helper()
	response := httptest.NewRecorder()
	handler.ServeHTTP(response, httptest.NewRequest(http.MethodGet, "/metrics", nil))
	if response.Code != http.StatusOK {
		t.Fatalf("scrape status %d", response.Code)
	}
	return response.Body.String()
}

func TestREDCountsCompletedBusinessRequestsOnly(t *testing.T) {
	next := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		status, _ := strconv.Atoi(r.Header.Get("X-Test-Status"))
		if status != 0 {
			w.WriteHeader(status)
		}
		fmt.Fprint(w, "unchanged response")
	})
	handler := InstrumentRED("orders", []string{"/orders/current"}, next)
	for _, status := range []int{200, 200, 400, 500} {
		request := httptest.NewRequest(http.MethodGet, "/orders/current?request_id=never-a-label", nil)
		request.Header.Set("X-Test-Status", strconv.Itoa(status))
		response := httptest.NewRecorder()
		handler.ServeHTTP(response, request)
		if response.Code != status || response.Body.String() != "unchanged response" {
			t.Fatalf("business response changed: %d %q", response.Code, response.Body.String())
		}
	}
	for _, path := range []string{"/health", "/debug/fault", "/not-found", "/metrics"} {
		handler.ServeHTTP(httptest.NewRecorder(), httptest.NewRequest(http.MethodGet, path, nil))
	}
	text := redScrape(t, handler)
	for class, expected := range map[string]float64{"1xx": 0, "2xx": 2, "3xx": 0, "4xx": 1, "5xx": 1, "unknown": 0} {
		if actual := redSample(t, text, "rca_http_server_requests_total", `status_class="`+class+`"`); actual != expected {
			t.Fatalf("%s count %g, want %g", class, actual, expected)
		}
	}
	if redSample(t, text, "rca_http_server_request_duration_seconds_count") != 4 ||
		redSample(t, text, "rca_http_server_request_duration_seconds_bucket", `le="+Inf"`) != 4 {
		t.Fatal("histogram denominator differs from completed requests")
	}
	if redSample(t, text, "rca_http_server_request_duration_seconds_sum") <= 0 {
		t.Fatal("duration was not observed")
	}
	if strings.Contains(text, "never-a-label") || strings.Contains(text, "request_id") || strings.Contains(text, "debug/fault") {
		t.Fatal("request identity leaked into metric labels")
	}
	response := httptest.NewRecorder()
	handler.ServeHTTP(response, httptest.NewRequest(http.MethodPost, "/metrics", nil))
	if response.Code != 405 || response.Header().Get("Allow") != "GET, HEAD" {
		t.Fatal("metrics endpoint accepted an unexpected method")
	}
}

func TestREDRegistriesAreIndependentAndConcurrent(t *testing.T) {
	next := http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) { w.WriteHeader(204) })
	first := InstrumentRED("gateway", []string{"/api/order"}, next)
	second := InstrumentRED("gateway", []string{"/api/order"}, next)
	var group sync.WaitGroup
	for i := 0; i < 100; i++ {
		group.Go(func() {
			first.ServeHTTP(httptest.NewRecorder(), httptest.NewRequest(http.MethodGet, "/api/order", nil))
		})
	}
	group.Wait()
	if redSample(t, redScrape(t, first), "rca_http_server_request_duration_seconds_count") != 100 ||
		redSample(t, redScrape(t, second), "rca_http_server_request_duration_seconds_count") != 0 {
		t.Fatal("parallel observations were lost or registries shared state")
	}
}

func TestREDRealHTTPWithoutTraceProvider(t *testing.T) {
	handler := InstrumentRED("payment", []string{"/payments/authorize"}, http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(http.StatusServiceUnavailable)
	}))
	server := httptest.NewServer(handler)
	defer server.Close()
	response, err := server.Client().Get(server.URL + "/payments/authorize")
	if err != nil {
		t.Fatal(err)
	}
	response.Body.Close()
	if response.StatusCode != 503 {
		t.Fatal("HTTP status changed")
	}
	response, err = server.Client().Get(server.URL + "/metrics")
	if err != nil {
		t.Fatal(err)
	}
	defer response.Body.Close()
	data, err := io.ReadAll(response.Body)
	if err != nil {
		t.Fatal(err)
	}
	if redSample(t, string(data), "rca_http_server_requests_total", `status_class="5xx"`) != 1 {
		t.Fatal("actual server failure was not observed independently of traces")
	}
}
