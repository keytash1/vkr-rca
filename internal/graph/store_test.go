package graph

import (
	"fmt"
	"reflect"
	"sync"
	"testing"
	"time"
)

func TestEmptyGraph(t *testing.T) {
	store := newTestStore(t)
	if got := store.Snapshot(); len(got.Nodes) != 0 || len(got.Edges) != 0 {
		t.Fatalf("empty snapshot = %+v", got)
	}
}

func TestSameServiceRelationshipCreatesNodeWithoutEdge(t *testing.T) {
	store := newTestStore(t)
	store.Ingest([]Span{
		testSpan("trace", "server", "", "gateway"),
		testSpan("trace", "client", "server", "gateway"),
	})

	want := Snapshot{Nodes: []Node{{Service: "gateway"}}, Edges: []Edge{}}
	assertTopology(t, store.Snapshot(), want)
}

func TestBuildsGatewayOrdersPaymentInCorrectDirection(t *testing.T) {
	store := newTestStore(t)
	result := store.Ingest(fiveSpanTrace("trace-1"))
	if result.Accepted != 5 || result.Duplicates != 0 || result.Ignored != 0 {
		t.Fatalf("ingest result = %+v", result)
	}

	want := Snapshot{
		Nodes: []Node{{Service: "gateway"}, {Service: "orders"}, {Service: "payment"}},
		Edges: []Edge{
			{Source: "gateway", Target: "orders", Observations: 1},
			{Source: "orders", Target: "payment", Observations: 1},
		},
	}
	assertTopology(t, store.Snapshot(), want)
}

func TestDuplicateSpansAreIdempotent(t *testing.T) {
	store := newTestStore(t)
	spans := fiveSpanTrace("trace-1")
	store.Ingest(spans)
	result := store.Ingest(spans)
	if result.Accepted != 0 || result.Duplicates != 5 {
		t.Fatalf("duplicate ingest result = %+v", result)
	}

	snapshot := store.Snapshot()
	for _, edge := range snapshot.Edges {
		if edge.Observations != 1 {
			t.Fatalf("edge %+v observations = %d, want 1", edge, edge.Observations)
		}
	}
}

func TestDifferentTracesIncreaseObservations(t *testing.T) {
	store := newTestStore(t)
	store.Ingest(fiveSpanTrace("trace-1"))
	store.Ingest(fiveSpanTrace("trace-2"))

	for _, edge := range store.Snapshot().Edges {
		if edge.Observations != 2 {
			t.Fatalf("edge %+v observations = %d, want 2", edge, edge.Observations)
		}
	}
}

func TestChildBeforeParent(t *testing.T) {
	store := newTestStore(t)
	child := testSpan("trace", "orders-server", "gateway-client", "orders")
	parent := testSpan("trace", "gateway-client", "gateway-server", "gateway")
	store.Ingest([]Span{child})
	if got := store.Snapshot(); len(got.Edges) != 0 {
		t.Fatalf("edge created before parent: %+v", got.Edges)
	}
	store.Ingest([]Span{parent})

	snapshot := store.Snapshot()
	if len(snapshot.Edges) != 1 || snapshot.Edges[0].Source != "gateway" || snapshot.Edges[0].Target != "orders" {
		t.Fatalf("out-of-order graph = %+v", snapshot)
	}
}

func TestMissingParentDoesNotCreateFalseEdge(t *testing.T) {
	store := newTestStore(t)
	store.Ingest([]Span{testSpan("trace", "orders", "unknown", "orders")})
	snapshot := store.Snapshot()
	if len(snapshot.Nodes) != 1 || len(snapshot.Edges) != 0 {
		t.Fatalf("missing-parent graph = %+v", snapshot)
	}
}

func TestMissingServiceIsIgnored(t *testing.T) {
	store := newTestStore(t)
	result := store.Ingest([]Span{testSpan("trace", "span", "", " ")})
	if result.Ignored != 1 || result.Accepted != 0 {
		t.Fatalf("ingest result = %+v", result)
	}
	if got := store.Snapshot(); len(got.Nodes) != 0 {
		t.Fatalf("ignored span created nodes: %+v", got.Nodes)
	}
}

func TestSnapshotOrderingIsDeterministic(t *testing.T) {
	store := newTestStore(t)
	store.Ingest([]Span{
		testSpan("trace-2", "z-parent", "", "zeta"),
		testSpan("trace-2", "a-child", "z-parent", "alpha"),
		testSpan("trace-1", "m-parent", "", "middle"),
		testSpan("trace-1", "z-child", "m-parent", "zeta"),
	})

	snapshot := store.Snapshot()
	wantNodes := []string{"alpha", "middle", "zeta"}
	for index, want := range wantNodes {
		if snapshot.Nodes[index].Service != want {
			t.Fatalf("nodes = %+v, want lexical ordering", snapshot.Nodes)
		}
	}
	if snapshot.Edges[0].Source != "middle" || snapshot.Edges[1].Source != "zeta" {
		t.Fatalf("edges = %+v, want lexical ordering", snapshot.Edges)
	}
}

func TestConcurrentIngestion(t *testing.T) {
	store := newTestStore(t)
	var waitGroup sync.WaitGroup
	for worker := 0; worker < 20; worker++ {
		waitGroup.Add(1)
		go func(worker int) {
			defer waitGroup.Done()
			for request := 0; request < 20; request++ {
				traceID := fmt.Sprintf("trace-%d-%d", worker, request)
				store.Ingest(fiveSpanTrace(traceID))
				_ = store.Snapshot()
			}
		}(worker)
	}
	waitGroup.Wait()

	snapshot := store.Snapshot()
	for _, edge := range snapshot.Edges {
		if edge.Observations != 400 {
			t.Fatalf("edge %+v observations = %d, want 400", edge, edge.Observations)
		}
	}
}

func TestTraceRetentionTTLAndLimitKeepAggregatedGraph(t *testing.T) {
	now := time.Date(2026, 9, 4, 0, 0, 0, 0, time.UTC)
	store, err := newStore(Config{TraceTTL: time.Minute, MaxTraces: 1}, func() time.Time { return now })
	if err != nil {
		t.Fatalf("new store: %v", err)
	}
	store.Ingest(fiveSpanTrace("trace-1"))
	store.Ingest(fiveSpanTrace("trace-2"))
	if _, found := store.Trace("trace-1"); found {
		t.Fatal("oldest trace retained above limit")
	}
	if _, found := store.Trace("trace-2"); !found {
		t.Fatal("newest trace was not retained")
	}

	now = now.Add(time.Minute)
	if _, found := store.Trace("trace-2"); found {
		t.Fatal("expired trace was retained")
	}
	if snapshot := store.Snapshot(); len(snapshot.Edges) != 2 || snapshot.Edges[0].Observations != 2 {
		t.Fatalf("aggregated graph was not retained: %+v", snapshot)
	}
}

func TestResetClearsTracesAndGraph(t *testing.T) {
	store := newTestStore(t)
	store.Ingest(fiveSpanTrace("trace"))
	store.Reset()
	if _, found := store.Trace("trace"); found {
		t.Fatal("trace survived reset")
	}
	if got := store.Snapshot(); len(got.Nodes) != 0 || len(got.Edges) != 0 {
		t.Fatalf("graph survived reset: %+v", got)
	}
}

func newTestStore(t *testing.T) *Store {
	t.Helper()
	store, err := NewStore(Config{TraceTTL: DefaultTraceTTL, MaxTraces: DefaultMaxTraces})
	if err != nil {
		t.Fatalf("new store: %v", err)
	}
	return store
}

func fiveSpanTrace(traceID string) []Span {
	return []Span{
		testSpan(traceID, "gateway-server", "", "gateway"),
		testSpan(traceID, "gateway-client", "gateway-server", "gateway"),
		testSpan(traceID, "orders-server", "gateway-client", "orders"),
		testSpan(traceID, "orders-client", "orders-server", "orders"),
		testSpan(traceID, "payment-server", "orders-client", "payment"),
	}
}

func testSpan(traceID, spanID, parentSpanID, service string) Span {
	start := time.Date(2026, 9, 4, 0, 0, 0, 0, time.UTC)
	return Span{
		TraceID:      traceID,
		SpanID:       spanID,
		ParentSpanID: parentSpanID,
		ServiceName:  service,
		StartTime:    start,
		EndTime:      start.Add(time.Millisecond),
		Duration:     time.Millisecond,
	}
}

func assertTopology(t *testing.T, got, want Snapshot) {
	t.Helper()
	for index := range got.Edges {
		got.Edges[index].FirstSeen = time.Time{}
		got.Edges[index].LastSeen = time.Time{}
	}
	if !reflect.DeepEqual(got, want) {
		t.Fatalf("snapshot = %+v, want %+v", got, want)
	}
}
