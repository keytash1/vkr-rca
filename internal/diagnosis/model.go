package diagnosis

import "time"

const (
	FeatureSchemaVersion                  = "m6-v1"
	DefaultMinActiveTopologyTraceCoverage = 0.7
)

type PrimarySignal string

const (
	SignalNone    PrimarySignal = "none"
	SignalLatency PrimarySignal = "latency"
	SignalError   PrimarySignal = "error"
)

type State string

const (
	StateBaselineNotFrozen State = "baseline_not_frozen"
	StateInsufficientData  State = "insufficient_current_data"
	StateNoAnomaly         State = "no_anomaly"
	StateReady             State = "ready"
)

type TopologySource string

const (
	TopologyActiveTraces   TopologySource = "active_traces"
	TopologyGlobalFallback TopologySource = "global_fallback"
)

type Edge struct {
	Caller string `json:"caller"`
	Callee string `json:"callee"`
}

type SampleRef struct {
	Service   string
	Operation string
	TraceID   string
	SpanID    string
	Timestamp time.Time
}

type OperationEvidence struct {
	Service          string
	Operation        string
	Ready            bool
	CurrentSamples   int
	LatencyZ         float64
	ErrorZ           float64
	LatencyAnomalous bool
	ErrorAnomalous   bool
	M5Severity       float64
	SampleRefs       []SampleRef
}

type SpanKind string

const (
	SpanKindServer   SpanKind = "server"
	SpanKindClient   SpanKind = "client"
	SpanKindInternal SpanKind = "internal"
	SpanKindOther    SpanKind = "other"
)

type TraceSpan struct {
	TraceID      string
	SpanID       string
	ParentSpanID string
	Service      string
	Kind         SpanKind
	StartTime    time.Time
	EndTime      time.Time
}

type Input struct {
	BaselineState                  string
	LatencyThreshold               float64
	ErrorThreshold                 float64
	MinActiveTopologyTraceCoverage float64
	Services                       []string
	Edges                          []Edge
	Operations                     []OperationEvidence
	Traces                         map[string][]TraceSpan
}

type TraceMeasurement struct {
	ServerDurationMS          float64 `json:"server_duration_ms"`
	DownstreamWaitObservedMS  float64 `json:"downstream_wait_observed_ms"`
	ExclusiveObservedDuration float64 `json:"exclusive_observed_duration_ms"`
	ExclusiveRatio            float64 `json:"exclusive_ratio"`
	DownstreamWaitRatio       float64 `json:"downstream_wait_ratio"`
}

type FeatureVector struct {
	Service                     string         `json:"service"`
	Ready                       bool           `json:"ready"`
	Candidate                   bool           `json:"candidate"`
	PrimarySignal               PrimarySignal  `json:"primary_signal"`
	TopologySource              TopologySource `json:"topology_source"`
	ActiveTopologyTraceCoverage float64        `json:"active_topology_trace_coverage"`

	LatencyZ         float64 `json:"latency_z"`
	ErrorZ           float64 `json:"error_z"`
	LatencyStrength  float64 `json:"latency_strength"`
	ErrorStrength    float64 `json:"error_strength"`
	LatencyAnomalous bool    `json:"latency_anomalous"`
	ErrorAnomalous   bool    `json:"error_anomalous"`
	M5Severity       float64 `json:"m5_severity"`

	SourceOperationLatency        string  `json:"source_operation_latency,omitempty"`
	SourceOperationError          string  `json:"source_operation_error,omitempty"`
	SourceOperationTrace          string  `json:"source_operation_trace,omitempty"`
	TraceOperationLatencyStrength float64 `json:"trace_operation_latency_strength"`

	TopologyPrecision        float64  `json:"topology_precision"`
	TopologyRecall           float64  `json:"topology_recall"`
	TopologyF1               float64  `json:"topology_f1"`
	ExpectedAffectedServices []string `json:"expected_affected_services"`

	CurrentSamples            int     `json:"current_samples"`
	TraceSamples              int     `json:"trace_samples"`
	TraceCoverage             float64 `json:"trace_coverage"`
	MedianExclusiveRatio      float64 `json:"median_exclusive_ratio"`
	MedianExclusiveDurationMS float64 `json:"median_exclusive_duration_ms"`
	MedianDownstreamWaitRatio float64 `json:"median_downstream_wait_ratio"`
	LocalEvidence             float64 `json:"local_evidence"`
}

type FeatureSnapshot struct {
	FeatureSchemaVersion        string          `json:"feature_schema_version"`
	BaselineState               string          `json:"baseline_state"`
	State                       State           `json:"state"`
	PrimarySignal               PrimarySignal   `json:"primary_signal"`
	TopologySource              TopologySource  `json:"topology_source"`
	ActiveTopologyTraceCoverage float64         `json:"active_topology_trace_coverage"`
	TopologyEdges               []Edge          `json:"topology_edges"`
	ReadyUniverse               []string        `json:"ready_universe"`
	ObservedAnomalies           []string        `json:"observed_anomalies"`
	Services                    []FeatureVector `json:"services"`
}

type TopologyEvidence struct {
	Precision           float64        `json:"precision"`
	Recall              float64        `json:"recall"`
	F1                  float64        `json:"f1"`
	ExpectedAffected    []string       `json:"expected_affected"`
	Source              TopologySource `json:"source"`
	ActiveTraceCoverage float64        `json:"active_trace_coverage"`
}

type SignalEvidence struct {
	Type     PrimarySignal `json:"type"`
	Z        float64       `json:"z"`
	Strength float64       `json:"strength"`
}

type TraceEvidence struct {
	ExclusiveRatio      float64 `json:"exclusive_ratio"`
	ExclusiveDurationMS float64 `json:"exclusive_duration_ms"`
	Coverage            float64 `json:"coverage"`
}

type CandidateEvidence struct {
	Topology      TopologyEvidence `json:"topology"`
	Signal        SignalEvidence   `json:"signal"`
	Trace         TraceEvidence    `json:"trace"`
	LocalEvidence float64          `json:"local_evidence"`
	M5Severity    float64          `json:"m5_severity"`
}

type RankedCandidate struct {
	Rank     int               `json:"rank"`
	Service  string            `json:"service"`
	Score    float64           `json:"score"`
	Evidence CandidateEvidence `json:"evidence"`
}

type Ranking []RankedCandidate

type RCASnapshot struct {
	FeatureSchemaVersion string             `json:"feature_schema_version"`
	State                State              `json:"state"`
	PrimarySignal        PrimarySignal      `json:"primary_signal"`
	ObservedAnomalies    []string           `json:"observed_anomalies"`
	Rankings             map[string]Ranking `json:"rankings"`
}
