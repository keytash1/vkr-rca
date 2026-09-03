package rca

import (
	"bytes"
	"context"
	"io"
	"log/slog"
	"testing"
	"time"

	collecttracev1 "go.opentelemetry.io/proto/otlp/collector/trace/v1"
	commonv1 "go.opentelemetry.io/proto/otlp/common/v1"
	resourcev1 "go.opentelemetry.io/proto/otlp/resource/v1"
	tracev1 "go.opentelemetry.io/proto/otlp/trace/v1"
	"vkr-rca/internal/graph"
)

func TestOTLPReceiverBuildsGraphFromFiveSpanHierarchy(t *testing.T) {
	store := newReceiverTestStore(t)
	receiver := NewReceiver(store, discardLogger())

	response, err := receiver.Export(context.Background(), fiveSpanOTLPRequest())
	if err != nil {
		t.Fatalf("export: %v", err)
	}
	if response.GetPartialSuccess().GetRejectedSpans() != 0 {
		t.Fatalf("partial success = %+v", response.GetPartialSuccess())
	}

	snapshot := store.Snapshot()
	if len(snapshot.Nodes) != 3 || len(snapshot.Edges) != 2 {
		t.Fatalf("graph = %+v", snapshot)
	}
	if snapshot.Edges[0].Source != "gateway" || snapshot.Edges[0].Target != "orders" ||
		snapshot.Edges[1].Source != "orders" || snapshot.Edges[1].Target != "payment" {
		t.Fatalf("unexpected topology: %+v", snapshot.Edges)
	}
	if stats := receiver.Stats(); stats.ReceivedSpans != 5 || stats.IgnoredSpans != 0 {
		t.Fatalf("receiver stats = %+v", stats)
	}

	traceID := bytes.Repeat([]byte{1}, 16)
	spans, found := store.Trace(hexID(traceID))
	if !found || len(spans) != 5 {
		t.Fatalf("normalized trace found=%v spans=%d", found, len(spans))
	}
	if spans[0].ServiceName != "gateway" || spans[0].Kind != graph.SpanKindServer {
		t.Fatalf("first normalized span = %+v", spans[0])
	}
}

func TestOTLPReceiverIgnoresMissingServiceAndInvalidIDs(t *testing.T) {
	store := newReceiverTestStore(t)
	receiver := NewReceiver(store, discardLogger())
	request := &collecttracev1.ExportTraceServiceRequest{ResourceSpans: []*tracev1.ResourceSpans{
		{
			Resource: resource(""),
			ScopeSpans: []*tracev1.ScopeSpans{{Spans: []*tracev1.Span{
				otlpSpan(1, 1, 0, tracev1.Span_SPAN_KIND_SERVER),
			}}},
		},
		{
			Resource: resource("gateway"),
			ScopeSpans: []*tracev1.ScopeSpans{{Spans: []*tracev1.Span{
				{TraceId: []byte{1}, SpanId: []byte{1}},
			}}},
		},
	}}

	response, err := receiver.Export(context.Background(), request)
	if err != nil {
		t.Fatalf("export: %v", err)
	}
	if response.GetPartialSuccess().GetRejectedSpans() != 2 {
		t.Fatalf("rejected spans = %d, want 2", response.GetPartialSuccess().GetRejectedSpans())
	}
	if got := store.Snapshot(); len(got.Nodes) != 0 {
		t.Fatalf("malformed spans created graph: %+v", got)
	}
	if stats := receiver.Stats(); stats.IgnoredSpans != 2 {
		t.Fatalf("receiver stats = %+v", stats)
	}
}

func TestOTLPReceiverDeduplicatesRetries(t *testing.T) {
	store := newReceiverTestStore(t)
	receiver := NewReceiver(store, discardLogger())
	request := fiveSpanOTLPRequest()
	if _, err := receiver.Export(context.Background(), request); err != nil {
		t.Fatalf("first export: %v", err)
	}
	if _, err := receiver.Export(context.Background(), request); err != nil {
		t.Fatalf("retry export: %v", err)
	}
	if stats := receiver.Stats(); stats.ReceivedSpans != 5 || stats.DuplicateSpans != 5 {
		t.Fatalf("receiver stats = %+v", stats)
	}
	for _, edge := range store.Snapshot().Edges {
		if edge.Observations != 1 {
			t.Fatalf("duplicate retry changed edge: %+v", edge)
		}
	}
}

func fiveSpanOTLPRequest() *collecttracev1.ExportTraceServiceRequest {
	return &collecttracev1.ExportTraceServiceRequest{ResourceSpans: []*tracev1.ResourceSpans{
		// Resources and spans are intentionally out of parent-first order.
		resourceSpans("payment", otlpSpan(1, 5, 4, tracev1.Span_SPAN_KIND_SERVER)),
		resourceSpans("orders",
			otlpSpan(1, 4, 3, tracev1.Span_SPAN_KIND_CLIENT),
			otlpSpan(1, 3, 2, tracev1.Span_SPAN_KIND_SERVER),
		),
		resourceSpans("gateway",
			otlpSpan(1, 2, 1, tracev1.Span_SPAN_KIND_CLIENT),
			otlpSpan(1, 1, 0, tracev1.Span_SPAN_KIND_SERVER),
		),
	}}
}

func resourceSpans(service string, spans ...*tracev1.Span) *tracev1.ResourceSpans {
	return &tracev1.ResourceSpans{
		Resource:   resource(service),
		ScopeSpans: []*tracev1.ScopeSpans{{Spans: spans}},
	}
}

func resource(service string) *resourcev1.Resource {
	attributes := []*commonv1.KeyValue{}
	if service != "" {
		attributes = append(attributes, &commonv1.KeyValue{
			Key: serviceNameAttribute,
			Value: &commonv1.AnyValue{Value: &commonv1.AnyValue_StringValue{
				StringValue: service,
			}},
		})
	}
	return &resourcev1.Resource{Attributes: attributes}
}

func otlpSpan(trace, span, parent byte, kind tracev1.Span_SpanKind) *tracev1.Span {
	start := time.Date(2026, 9, 4, 0, 0, int(span), 0, time.UTC)
	var parentID []byte
	if parent != 0 {
		parentID = bytes.Repeat([]byte{parent}, 8)
	}
	return &tracev1.Span{
		TraceId:           bytes.Repeat([]byte{trace}, 16),
		SpanId:            bytes.Repeat([]byte{span}, 8),
		ParentSpanId:      parentID,
		Name:              "test span",
		Kind:              kind,
		StartTimeUnixNano: uint64(start.UnixNano()),
		EndTimeUnixNano:   uint64(start.Add(time.Millisecond).UnixNano()),
		Status:            &tracev1.Status{Code: tracev1.Status_STATUS_CODE_OK},
	}
}

func newReceiverTestStore(t *testing.T) *graph.Store {
	t.Helper()
	store, err := graph.NewStore(graph.Config{TraceTTL: graph.DefaultTraceTTL, MaxTraces: graph.DefaultMaxTraces})
	if err != nil {
		t.Fatalf("new store: %v", err)
	}
	return store
}

func discardLogger() *slog.Logger {
	return slog.New(slog.NewTextHandler(io.Discard, nil))
}

func hexID(value []byte) string {
	const digits = "0123456789abcdef"
	encoded := make([]byte, len(value)*2)
	for index, part := range value {
		encoded[index*2] = digits[part>>4]
		encoded[index*2+1] = digits[part&0x0f]
	}
	return string(encoded)
}
