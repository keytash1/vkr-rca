package externalrca

import (
	"testing"
)

func TestProcessReusesM5M6ForExternalSpans(t *testing.T) {
	inject := int64(1_700_000_000)
	spans := make([]Span, 0)
	for index := 0; index < 40; index++ {
		spans = append(spans, tracePair(inject-500+int64(index), index, 1_000, nil)...)
	}
	for index := 0; index < 20; index++ {
		spans = append(spans, tracePair(inject+int64(index), 100+index, 700_000, nil)...)
	}
	output, err := Process(Input{ExternalCaseID: "opaque-case", InjectUnix: inject, Mode: ModeFault, Spans: spans})
	if err != nil {
		t.Fatal(err)
	}
	if output.Features.State != "ready" {
		t.Fatalf("state = %s", output.Features.State)
	}
	if len(output.RCA.Rankings["hybrid_v1"]) == 0 || output.RCA.Rankings["hybrid_v1"][0].Service != "leaf" {
		t.Fatalf("ranking = %#v", output.RCA.Rankings["hybrid_v1"])
	}
	if output.Coverage.ExclusiveTraceCoverage != 1 {
		t.Fatalf("exclusive coverage = %v", output.Coverage.ExclusiveTraceCoverage)
	}
}

func TestHealthyWindowsDoNotOverlapPostInjection(t *testing.T) {
	inject := int64(1_700_000_000)
	spans := make([]Span, 0)
	for index := 0; index < 40; index++ {
		spans = append(spans, tracePair(inject-500+int64(index), index, 1_000, nil)...)
		spans = append(spans, tracePair(inject-200+int64(index), 100+index, 1_000, nil)...)
		spans = append(spans, tracePair(inject+int64(index), 200+index, 900_000, nil)...)
	}
	output, err := Process(Input{ExternalCaseID: "opaque-healthy", InjectUnix: inject, Mode: ModeHealthy, Spans: spans})
	if err != nil {
		t.Fatal(err)
	}
	if output.Features.State != "no_anomaly" {
		t.Fatalf("post-injection data leaked into healthy current: %s", output.Features.State)
	}
}

func TestMissingParentIsNotInferredAsServer(t *testing.T) {
	spans := []Span{{TraceID: "t", SpanID: "child", ParentSpanID: "absent", Service: "svc", Operation: "op", StartUnixUS: 1, DurationUS: 1}}
	inferred, coverage := inferKinds(spans)
	if inferred[0].kind == "server" {
		t.Fatal("span with non-empty missing parent inferred as server")
	}
	if coverage.ParentMatchRate != 0 {
		t.Fatalf("parent match = %v", coverage.ParentMatchRate)
	}
}

func TestStatusMapping(t *testing.T) {
	zero, grpc, http, missing := int64(0), int64(14), int64(500), (*int64)(nil)
	if failed(&zero) || !failed(&grpc) || !failed(&http) || failed(missing) {
		t.Fatal("unexpected status mapping")
	}
}

func tracePair(second int64, index int, leafDurationUS int64, code *int64) []Span {
	trace := "trace-" + string(rune(index+1000))
	root := "root-" + string(rune(index+1000))
	client := "client-" + string(rune(index+1000))
	leaf := "leaf-" + string(rune(index+1000))
	start := second * 1_000_000
	return []Span{
		{TraceID: trace, SpanID: root, Service: "entry", Operation: "GET /work", StartUnixUS: start, DurationUS: int64(leafDurationUS + 2_000), StatusCode: code},
		{TraceID: trace, SpanID: client, ParentSpanID: root, Service: "entry", Operation: "GET leaf", StartUnixUS: start + 500, DurationUS: int64(leafDurationUS + 1_000), StatusCode: code},
		{TraceID: trace, SpanID: leaf, ParentSpanID: client, Service: "leaf", Operation: "GET /work", StartUnixUS: start + 1_000, DurationUS: int64(leafDurationUS), StatusCode: code},
	}
}
