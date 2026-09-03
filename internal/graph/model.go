package graph

import "time"

type SpanKind string

const (
	SpanKindUnspecified SpanKind = "unspecified"
	SpanKindInternal    SpanKind = "internal"
	SpanKindServer      SpanKind = "server"
	SpanKindClient      SpanKind = "client"
	SpanKindProducer    SpanKind = "producer"
	SpanKindConsumer    SpanKind = "consumer"
)

type StatusCode string

const (
	StatusUnset StatusCode = "unset"
	StatusOK    StatusCode = "ok"
	StatusError StatusCode = "error"
)

type Span struct {
	TraceID      string        `json:"trace_id"`
	SpanID       string        `json:"span_id"`
	ParentSpanID string        `json:"parent_span_id,omitempty"`
	ServiceName  string        `json:"service"`
	Name         string        `json:"name"`
	Kind         SpanKind      `json:"kind"`
	StartTime    time.Time     `json:"start_time"`
	EndTime      time.Time     `json:"end_time"`
	Duration     time.Duration `json:"duration_ns"`
	StatusCode   StatusCode    `json:"status_code"`
	HTTPMethod   string        `json:"http_method,omitempty"`
	HTTPRoute    string        `json:"http_route,omitempty"`
	HTTPStatus   int64         `json:"http_status,omitempty"`
}

type Node struct {
	Service string `json:"service"`
}

type Edge struct {
	Source       string    `json:"source"`
	Target       string    `json:"target"`
	Observations uint64    `json:"observations"`
	FirstSeen    time.Time `json:"first_seen"`
	LastSeen     time.Time `json:"last_seen"`
}

type Snapshot struct {
	Nodes []Node `json:"nodes"`
	Edges []Edge `json:"edges"`
}

type IngestResult struct {
	Accepted   uint64
	Duplicates uint64
	Ignored    uint64
}
