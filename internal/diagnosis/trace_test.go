package diagnosis

import (
	"math"
	"testing"
	"time"
)

func TestExclusiveObservedLeafAndSingleClient(t *testing.T) {
	base := time.Unix(0, 0)
	leaf := serverSpan("server", "service", base, base.Add(700*time.Millisecond))
	measurement, valid := ExclusiveObserved([]TraceSpan{leaf}, "server")
	if !valid || measurement.ExclusiveRatio != 1 || measurement.ExclusiveObservedDuration != 700 {
		t.Fatalf("leaf measurement = %+v valid=%v", measurement, valid)
	}

	client := TraceSpan{SpanID: "client", ParentSpanID: "server", Service: "service", Kind: SpanKindClient, StartTime: base.Add(time.Millisecond), EndTime: base.Add(699 * time.Millisecond)}
	measurement, valid = ExclusiveObserved([]TraceSpan{leaf, client}, "server")
	if !valid || math.Abs(measurement.ExclusiveObservedDuration-2) > 1e-9 {
		t.Fatalf("single client measurement = %+v valid=%v", measurement, valid)
	}
}

func TestExclusiveObservedLocalDelaySequentialAndOverlappingClients(t *testing.T) {
	base := time.Unix(0, 0)
	tests := []struct {
		name          string
		serverEnd     time.Duration
		clients       []TraceSpan
		wantWaitMS    float64
		wantExclusive float64
	}{
		{
			name: "local delay and short downstream", serverEnd: 710 * time.Millisecond,
			clients:    []TraceSpan{clientSpan("c", "s", "svc", base.Add(700*time.Millisecond), base.Add(710*time.Millisecond))},
			wantWaitMS: 10, wantExclusive: 700,
		},
		{
			name: "sequential", serverEnd: 100 * time.Millisecond,
			clients: []TraceSpan{
				clientSpan("a", "s", "svc", base.Add(10*time.Millisecond), base.Add(30*time.Millisecond)),
				clientSpan("b", "s", "svc", base.Add(40*time.Millisecond), base.Add(60*time.Millisecond)),
			},
			wantWaitMS: 40, wantExclusive: 60,
		},
		{
			name: "overlap", serverEnd: 100 * time.Millisecond,
			clients: []TraceSpan{
				clientSpan("a", "s", "svc", base.Add(10*time.Millisecond), base.Add(50*time.Millisecond)),
				clientSpan("b", "s", "svc", base.Add(30*time.Millisecond), base.Add(70*time.Millisecond)),
			},
			wantWaitMS: 60, wantExclusive: 40,
		},
		{
			name: "fully overlapping", serverEnd: 100 * time.Millisecond,
			clients: []TraceSpan{
				clientSpan("a", "s", "svc", base.Add(10*time.Millisecond), base.Add(50*time.Millisecond)),
				clientSpan("b", "s", "svc", base.Add(10*time.Millisecond), base.Add(50*time.Millisecond)),
			},
			wantWaitMS: 40, wantExclusive: 60,
		},
		{
			name: "clipped", serverEnd: 100 * time.Millisecond,
			clients: []TraceSpan{
				clientSpan("a", "s", "svc", base.Add(-10*time.Millisecond), base.Add(20*time.Millisecond)),
				clientSpan("b", "s", "svc", base.Add(90*time.Millisecond), base.Add(120*time.Millisecond)),
			},
			wantWaitMS: 30, wantExclusive: 70,
		},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			spans := append([]TraceSpan{serverSpan("s", "svc", base, base.Add(test.serverEnd))}, test.clients...)
			measurement, valid := ExclusiveObserved(spans, "s")
			if !valid || math.Abs(measurement.DownstreamWaitObservedMS-test.wantWaitMS) > 1e-9 ||
				math.Abs(measurement.ExclusiveObservedDuration-test.wantExclusive) > 1e-9 {
				t.Fatalf("measurement = %+v valid=%v", measurement, valid)
			}
		})
	}
}

func TestExclusiveObservedUsesHierarchyAndSameServiceOnly(t *testing.T) {
	base := time.Unix(0, 0)
	spans := []TraceSpan{
		serverSpan("s", "svc", base, base.Add(100*time.Millisecond)),
		{SpanID: "internal", ParentSpanID: "s", Service: "svc", Kind: SpanKindInternal, StartTime: base, EndTime: base.Add(100 * time.Millisecond)},
		clientSpan("local", "internal", "svc", base.Add(10*time.Millisecond), base.Add(70*time.Millisecond)),
		clientSpan("remote", "s", "other", base, base.Add(100*time.Millisecond)),
		clientSpan("contained-not-descendant", "missing", "svc", base, base.Add(100*time.Millisecond)),
	}
	measurement, valid := ExclusiveObserved(spans, "s")
	if !valid || measurement.DownstreamWaitObservedMS != 60 || measurement.ExclusiveObservedDuration != 40 {
		t.Fatalf("measurement = %+v valid=%v", measurement, valid)
	}
}

func TestExclusiveObservedRejectsMissingAndMalformedServers(t *testing.T) {
	base := time.Unix(0, 0)
	for _, spans := range [][]TraceSpan{
		nil,
		{serverSpan("s", "svc", base, base)},
		{{SpanID: "s", Service: "svc", Kind: SpanKindClient, StartTime: base, EndTime: base.Add(time.Second)}},
	} {
		if measurement, valid := ExclusiveObserved(spans, "s"); valid || measurement != (TraceMeasurement{}) {
			t.Fatalf("malformed measurement = %+v valid=%v", measurement, valid)
		}
	}
}

func TestMissingTraceLowersCoverageWithoutFabricatingRatio(t *testing.T) {
	input := activeGraphInput()
	input.Operations = input.Operations[:1]
	input.Operations[0].CurrentSamples = 2
	input.Operations[0].SampleRefs = append(input.Operations[0].SampleRefs,
		SampleRef{Service: "gateway", Operation: "GET /operation", TraceID: "missing", SpanID: "missing"},
	)
	feature := featureByService(t, BuildFeatures(input), "gateway")
	if feature.TraceSamples != 1 || feature.CurrentSamples != 2 || feature.TraceCoverage != 0.5 {
		t.Fatalf("coverage feature = %+v", feature)
	}
	if feature.MedianExclusiveRatio == 0 {
		t.Fatalf("missing trace fabricated zero ratio: %+v", feature)
	}
}

func serverSpan(id, service string, start, end time.Time) TraceSpan {
	return TraceSpan{SpanID: id, Service: service, Kind: SpanKindServer, StartTime: start, EndTime: end}
}

func clientSpan(id, parent, service string, start, end time.Time) TraceSpan {
	return TraceSpan{SpanID: id, ParentSpanID: parent, Service: service, Kind: SpanKindClient, StartTime: start, EndTime: end}
}
