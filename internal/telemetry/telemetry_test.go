package telemetry

import (
	"context"
	"testing"

	"go.opentelemetry.io/otel/baggage"
	"go.opentelemetry.io/otel/propagation"
	"go.opentelemetry.io/otel/trace"
)

func TestPropagatorRoundTrip(t *testing.T) {
	traceID := trace.TraceID{1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16}
	spanID := trace.SpanID{1, 2, 3, 4, 5, 6, 7, 8}
	spanContext := trace.NewSpanContext(trace.SpanContextConfig{
		TraceID:    traceID,
		SpanID:     spanID,
		TraceFlags: trace.FlagsSampled,
		Remote:     true,
	})
	member, err := baggage.NewMember("scenario", "milestone-2")
	if err != nil {
		t.Fatalf("create baggage member: %v", err)
	}
	bag, err := baggage.New(member)
	if err != nil {
		t.Fatalf("create baggage: %v", err)
	}

	ctx := trace.ContextWithRemoteSpanContext(context.Background(), spanContext)
	ctx = baggage.ContextWithBaggage(ctx, bag)
	carrier := propagation.MapCarrier{}
	Propagator().Inject(ctx, carrier)

	extracted := Propagator().Extract(context.Background(), carrier)
	extractedSpan := trace.SpanContextFromContext(extracted)
	if extractedSpan.TraceID() != traceID || extractedSpan.SpanID() != spanID {
		t.Fatalf("extracted span context = %s/%s, want %s/%s",
			extractedSpan.TraceID(), extractedSpan.SpanID(), traceID, spanID)
	}
	if got := baggage.FromContext(extracted).Member("scenario").Value(); got != "milestone-2" {
		t.Fatalf("extracted baggage = %q, want milestone-2", got)
	}
}

func TestInitTracerProviderValidatesConfig(t *testing.T) {
	tests := []Config{
		{OTLPEndpoint: "collector:4317"},
		{ServiceName: "gateway"},
	}

	for _, config := range tests {
		if _, err := InitTracerProvider(context.Background(), config); err == nil {
			t.Fatalf("InitTracerProvider(%+v) returned no error", config)
		}
	}
}
