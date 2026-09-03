package graph

import (
	"errors"
	"sort"
	"strings"
	"sync"
	"time"
)

const (
	DefaultTraceTTL  = 10 * time.Minute
	DefaultMaxTraces = 5000
)

type Config struct {
	TraceTTL  time.Duration
	MaxTraces int
}

type Store struct {
	mu sync.Mutex

	traceTTL  time.Duration
	maxTraces int
	now       func() time.Time

	traces map[string]*traceState
	nodes  map[string]struct{}
	edges  map[edgeKey]Edge
}

type traceState struct {
	spans            map[string]Span
	childrenByParent map[string]map[string]struct{}
	linkedChildren   map[string]struct{}
	lastUpdated      time.Time
}

type edgeKey struct {
	source string
	target string
}

func NewStore(config Config) (*Store, error) {
	return newStore(config, time.Now)
}

func newStore(config Config, now func() time.Time) (*Store, error) {
	if config.TraceTTL <= 0 {
		return nil, errors.New("trace TTL must be greater than zero")
	}
	if config.MaxTraces <= 0 {
		return nil, errors.New("max traces must be greater than zero")
	}
	if now == nil {
		return nil, errors.New("clock is required")
	}

	store := &Store{
		traceTTL:  config.TraceTTL,
		maxTraces: config.MaxTraces,
		now:       now,
	}
	store.resetLocked()
	return store, nil
}

func (store *Store) Ingest(spans []Span) IngestResult {
	store.mu.Lock()
	defer store.mu.Unlock()

	now := store.now()
	store.cleanupLocked(now)

	var result IngestResult
	for _, span := range spans {
		span.TraceID = strings.TrimSpace(span.TraceID)
		span.SpanID = strings.TrimSpace(span.SpanID)
		span.ParentSpanID = strings.TrimSpace(span.ParentSpanID)
		span.ServiceName = strings.TrimSpace(span.ServiceName)
		if span.TraceID == "" || span.SpanID == "" || span.ServiceName == "" {
			result.Ignored++
			continue
		}

		trace := store.traces[span.TraceID]
		if trace == nil {
			store.ensureCapacityLocked()
			trace = &traceState{
				spans:            make(map[string]Span),
				childrenByParent: make(map[string]map[string]struct{}),
				linkedChildren:   make(map[string]struct{}),
			}
			store.traces[span.TraceID] = trace
		}
		trace.lastUpdated = now

		if _, exists := trace.spans[span.SpanID]; exists {
			result.Duplicates++
			continue
		}

		trace.spans[span.SpanID] = span
		store.nodes[span.ServiceName] = struct{}{}
		result.Accepted++

		if span.ParentSpanID != "" {
			children := trace.childrenByParent[span.ParentSpanID]
			if children == nil {
				children = make(map[string]struct{})
				trace.childrenByParent[span.ParentSpanID] = children
			}
			children[span.SpanID] = struct{}{}
			store.linkChildLocked(trace, span.SpanID, now)
		}

		for childID := range trace.childrenByParent[span.SpanID] {
			store.linkChildLocked(trace, childID, now)
		}
	}

	return result
}

func (store *Store) Snapshot() Snapshot {
	store.mu.Lock()
	defer store.mu.Unlock()

	store.cleanupLocked(store.now())
	snapshot := Snapshot{
		Nodes: make([]Node, 0, len(store.nodes)),
		Edges: make([]Edge, 0, len(store.edges)),
	}
	for service := range store.nodes {
		snapshot.Nodes = append(snapshot.Nodes, Node{Service: service})
	}
	for _, edge := range store.edges {
		snapshot.Edges = append(snapshot.Edges, edge)
	}

	sort.Slice(snapshot.Nodes, func(left, right int) bool {
		return snapshot.Nodes[left].Service < snapshot.Nodes[right].Service
	})
	sort.Slice(snapshot.Edges, func(left, right int) bool {
		if snapshot.Edges[left].Source != snapshot.Edges[right].Source {
			return snapshot.Edges[left].Source < snapshot.Edges[right].Source
		}
		return snapshot.Edges[left].Target < snapshot.Edges[right].Target
	})
	return snapshot
}

func (store *Store) Trace(traceID string) ([]Span, bool) {
	store.mu.Lock()
	defer store.mu.Unlock()

	store.cleanupLocked(store.now())
	trace := store.traces[strings.TrimSpace(traceID)]
	if trace == nil {
		return nil, false
	}

	spans := make([]Span, 0, len(trace.spans))
	for _, span := range trace.spans {
		spans = append(spans, span)
	}
	sort.Slice(spans, func(left, right int) bool {
		if !spans[left].StartTime.Equal(spans[right].StartTime) {
			return spans[left].StartTime.Before(spans[right].StartTime)
		}
		return spans[left].SpanID < spans[right].SpanID
	})
	return spans, true
}

func (store *Store) Reset() {
	store.mu.Lock()
	defer store.mu.Unlock()
	store.resetLocked()
}

func (store *Store) linkChildLocked(trace *traceState, childID string, now time.Time) {
	if _, linked := trace.linkedChildren[childID]; linked {
		return
	}
	child, childExists := trace.spans[childID]
	if !childExists || child.ParentSpanID == "" {
		return
	}
	parent, parentExists := trace.spans[child.ParentSpanID]
	if !parentExists {
		return
	}

	trace.linkedChildren[childID] = struct{}{}
	if parent.ServiceName == child.ServiceName {
		return
	}

	observedAt := child.StartTime
	if observedAt.IsZero() {
		observedAt = now
	}
	key := edgeKey{source: parent.ServiceName, target: child.ServiceName}
	edge, exists := store.edges[key]
	if !exists {
		store.edges[key] = Edge{
			Source:       key.source,
			Target:       key.target,
			Observations: 1,
			FirstSeen:    observedAt,
			LastSeen:     observedAt,
		}
		return
	}

	edge.Observations++
	if observedAt.Before(edge.FirstSeen) {
		edge.FirstSeen = observedAt
	}
	if observedAt.After(edge.LastSeen) {
		edge.LastSeen = observedAt
	}
	store.edges[key] = edge
}

func (store *Store) cleanupLocked(now time.Time) {
	for traceID, trace := range store.traces {
		if now.Sub(trace.lastUpdated) >= store.traceTTL {
			delete(store.traces, traceID)
		}
	}
}

func (store *Store) ensureCapacityLocked() {
	if len(store.traces) < store.maxTraces {
		return
	}

	var oldestID string
	var oldestTime time.Time
	for traceID, trace := range store.traces {
		if oldestID == "" || trace.lastUpdated.Before(oldestTime) ||
			(trace.lastUpdated.Equal(oldestTime) && traceID < oldestID) {
			oldestID = traceID
			oldestTime = trace.lastUpdated
		}
	}
	delete(store.traces, oldestID)
}

func (store *Store) resetLocked() {
	store.traces = make(map[string]*traceState)
	store.nodes = make(map[string]struct{})
	store.edges = make(map[edgeKey]Edge)
}
