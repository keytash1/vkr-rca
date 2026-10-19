package telemetry

import (
	"net/http"
	"strconv"

	"github.com/felixge/httpsnoop"
	"github.com/prometheus/client_golang/prometheus"
	"github.com/prometheus/client_golang/prometheus/promhttp"
)

// InstrumentRED observes completed business requests independently of traces.
// Only the supplied exact paths are measured. Paths, IDs and fault controls
// never become metric labels; each handler owns its own bounded registry.
func InstrumentRED(serviceName string, businessPaths []string, next http.Handler) http.Handler {
	registry := prometheus.NewRegistry()
	requests := prometheus.NewCounterVec(prometheus.CounterOpts{
		Name:        "rca_http_server_requests_total",
		Help:        "Completed business HTTP requests by response status class.",
		ConstLabels: prometheus.Labels{"service": serviceName},
	}, []string{"status_class"})
	duration := prometheus.NewHistogram(prometheus.HistogramOpts{
		Name:        "rca_http_server_request_duration_seconds",
		Help:        "Server-side duration of completed business HTTP requests in seconds.",
		ConstLabels: prometheus.Labels{"service": serviceName},
		Buckets:     []float64{.005, .01, .025, .05, .1, .25, .5, 1, 2.5, 5, 10},
	})
	registry.MustRegister(requests, duration)
	for _, class := range []string{"1xx", "2xx", "3xx", "4xx", "5xx", "unknown"} {
		requests.WithLabelValues(class).Add(0)
	}
	metrics := promhttp.HandlerFor(registry, promhttp.HandlerOpts{})
	paths := make(map[string]bool, len(businessPaths))
	for _, path := range businessPaths {
		paths[path] = true
	}
	return http.HandlerFunc(func(writer http.ResponseWriter, request *http.Request) {
		if request.URL.Path == "/metrics" {
			if request.Method != http.MethodGet && request.Method != http.MethodHead {
				writer.Header().Set("Allow", "GET, HEAD")
				writer.WriteHeader(http.StatusMethodNotAllowed)
				return
			}
			metrics.ServeHTTP(writer, request)
			return
		}
		if !paths[request.URL.Path] {
			next.ServeHTTP(writer, request)
			return
		}
		observed := httpsnoop.CaptureMetrics(next, writer, request)
		class := "unknown"
		if observed.Code >= 100 && observed.Code < 600 {
			class = strconv.Itoa(observed.Code/100) + "xx"
		}
		requests.WithLabelValues(class).Inc()
		duration.Observe(observed.Duration.Seconds())
	})
}
