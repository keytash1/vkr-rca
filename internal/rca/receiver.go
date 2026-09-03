package rca

import (
	"context"
	"encoding/hex"
	"log/slog"
	"strings"
	"sync/atomic"
	"time"

	collecttracev1 "go.opentelemetry.io/proto/otlp/collector/trace/v1"
	commonv1 "go.opentelemetry.io/proto/otlp/common/v1"
	tracev1 "go.opentelemetry.io/proto/otlp/trace/v1"
	_ "google.golang.org/grpc/encoding/gzip"
	"vkr-rca/internal/graph"
)

const serviceNameAttribute = "service.name"

type Receiver struct {
	collecttracev1.UnimplementedTraceServiceServer

	store  *graph.Store
	logger *slog.Logger

	receivedSpans  atomic.Uint64
	duplicateSpans atomic.Uint64
	ignoredSpans   atomic.Uint64
}

type ReceiverStats struct {
	ReceivedSpans  uint64
	DuplicateSpans uint64
	IgnoredSpans   uint64
}

func NewReceiver(store *graph.Store, logger *slog.Logger) *Receiver {
	return &Receiver{store: store, logger: logger}
}

func (receiver *Receiver) Export(
	ctx context.Context,
	request *collecttracev1.ExportTraceServiceRequest,
) (*collecttracev1.ExportTraceServiceResponse, error) {
	spans, malformed := normalizeRequest(request)
	result := receiver.store.Ingest(spans)
	ignored := malformed + result.Ignored

	receiver.receivedSpans.Add(result.Accepted)
	receiver.duplicateSpans.Add(result.Duplicates)
	receiver.ignoredSpans.Add(ignored)

	response := &collecttracev1.ExportTraceServiceResponse{}
	if ignored > 0 {
		response.PartialSuccess = &collecttracev1.ExportTracePartialSuccess{
			RejectedSpans: int64(ignored),
			ErrorMessage:  "spans with invalid identity or missing service.name were ignored",
		}
		receiver.logger.WarnContext(ctx, "ignored malformed telemetry",
			"ignored_spans", ignored,
		)
	}
	return response, nil
}

func (receiver *Receiver) Stats() ReceiverStats {
	return ReceiverStats{
		ReceivedSpans:  receiver.receivedSpans.Load(),
		DuplicateSpans: receiver.duplicateSpans.Load(),
		IgnoredSpans:   receiver.ignoredSpans.Load(),
	}
}

func normalizeRequest(request *collecttracev1.ExportTraceServiceRequest) ([]graph.Span, uint64) {
	if request == nil {
		return nil, 0
	}

	var spans []graph.Span
	var malformed uint64
	for _, resourceSpans := range request.ResourceSpans {
		serviceName := resourceServiceName(resourceSpans.GetResource().GetAttributes())
		for _, scopeSpans := range resourceSpans.GetScopeSpans() {
			for _, otlpSpan := range scopeSpans.GetSpans() {
				span, valid := normalizeSpan(serviceName, otlpSpan)
				if !valid {
					malformed++
					continue
				}
				spans = append(spans, span)
			}
		}
	}
	return spans, malformed
}

func normalizeSpan(serviceName string, otlpSpan *tracev1.Span) (graph.Span, bool) {
	if otlpSpan == nil || strings.TrimSpace(serviceName) == "" ||
		!validID(otlpSpan.GetTraceId(), 16) || !validID(otlpSpan.GetSpanId(), 8) {
		return graph.Span{}, false
	}
	if parent := otlpSpan.GetParentSpanId(); len(parent) != 0 && !validID(parent, 8) {
		return graph.Span{}, false
	}

	startTime := unixNano(otlpSpan.GetStartTimeUnixNano())
	endTime := unixNano(otlpSpan.GetEndTimeUnixNano())
	duration := time.Duration(0)
	if !startTime.IsZero() && !endTime.Before(startTime) {
		duration = endTime.Sub(startTime)
	}

	httpMethod, httpRoute, httpStatus := httpAttributes(otlpSpan.GetAttributes())
	return graph.Span{
		TraceID:      hex.EncodeToString(otlpSpan.GetTraceId()),
		SpanID:       hex.EncodeToString(otlpSpan.GetSpanId()),
		ParentSpanID: hex.EncodeToString(otlpSpan.GetParentSpanId()),
		ServiceName:  strings.TrimSpace(serviceName),
		Name:         otlpSpan.GetName(),
		Kind:         normalizeKind(otlpSpan.GetKind()),
		StartTime:    startTime,
		EndTime:      endTime,
		Duration:     duration,
		StatusCode:   normalizeStatus(otlpSpan.GetStatus().GetCode()),
		HTTPMethod:   httpMethod,
		HTTPRoute:    httpRoute,
		HTTPStatus:   httpStatus,
	}, true
}

func resourceServiceName(attributes []*commonv1.KeyValue) string {
	for _, attribute := range attributes {
		if attribute.GetKey() == serviceNameAttribute {
			return attribute.GetValue().GetStringValue()
		}
	}
	return ""
}

func httpAttributes(attributes []*commonv1.KeyValue) (method, route string, status int64) {
	for _, attribute := range attributes {
		switch attribute.GetKey() {
		case "http.request.method", "http.method":
			method = attribute.GetValue().GetStringValue()
		case "http.route":
			route = attribute.GetValue().GetStringValue()
		case "http.response.status_code", "http.status_code":
			status = attribute.GetValue().GetIntValue()
		}
	}
	return method, route, status
}

func normalizeKind(kind tracev1.Span_SpanKind) graph.SpanKind {
	switch kind {
	case tracev1.Span_SPAN_KIND_INTERNAL:
		return graph.SpanKindInternal
	case tracev1.Span_SPAN_KIND_SERVER:
		return graph.SpanKindServer
	case tracev1.Span_SPAN_KIND_CLIENT:
		return graph.SpanKindClient
	case tracev1.Span_SPAN_KIND_PRODUCER:
		return graph.SpanKindProducer
	case tracev1.Span_SPAN_KIND_CONSUMER:
		return graph.SpanKindConsumer
	default:
		return graph.SpanKindUnspecified
	}
}

func normalizeStatus(status tracev1.Status_StatusCode) graph.StatusCode {
	switch status {
	case tracev1.Status_STATUS_CODE_OK:
		return graph.StatusOK
	case tracev1.Status_STATUS_CODE_ERROR:
		return graph.StatusError
	default:
		return graph.StatusUnset
	}
}

func validID(value []byte, length int) bool {
	if len(value) != length {
		return false
	}
	for _, part := range value {
		if part != 0 {
			return true
		}
	}
	return false
}

func unixNano(value uint64) time.Time {
	if value == 0 {
		return time.Time{}
	}
	return time.Unix(0, int64(value)).UTC()
}
