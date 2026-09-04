package rca

import (
	"strings"

	"vkr-rca/internal/anomaly"
	"vkr-rca/internal/graph"
)

type SpanObserver interface {
	ObserveSpan(graph.Span)
}

type anomalyObserver struct {
	detector *anomaly.Detector
}

func NewAnomalyObserver(detector *anomaly.Detector) SpanObserver {
	return &anomalyObserver{detector: detector}
}

func (observer *anomalyObserver) ObserveSpan(span graph.Span) {
	if span.Kind != graph.SpanKindServer {
		return
	}

	operation := operationName(span)
	if operation == "" || ignoredOperation(operation) {
		return
	}

	failed := span.HTTPStatus >= 500
	if span.HTTPStatus == 0 {
		failed = span.StatusCode == graph.StatusError
	}
	observer.detector.Observe(anomaly.Observation{
		Key: anomaly.OperationKey{
			Service:   span.ServiceName,
			Operation: operation,
		},
		TraceID:   span.TraceID,
		SpanID:    span.SpanID,
		Timestamp: span.EndTime,
		Latency:   span.Duration,
		Failed:    failed,
	})
}

func operationName(span graph.Span) string {
	route := strings.TrimSpace(span.HTTPRoute)
	if route == "" {
		return strings.TrimSpace(span.Name)
	}
	method := strings.TrimSpace(span.HTTPMethod)
	if method == "" {
		return route
	}
	return method + " " + route
}

func ignoredOperation(operation string) bool {
	parts := strings.Fields(operation)
	path := operation
	if len(parts) > 1 {
		path = parts[len(parts)-1]
	}
	return path == "/health" || strings.HasPrefix(path, "/debug/")
}
