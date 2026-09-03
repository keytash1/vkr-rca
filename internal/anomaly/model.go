package anomaly

import "time"

type BaselineState string

const (
	StateEmpty      BaselineState = "empty"
	StateCollecting BaselineState = "collecting"
	StateFrozen     BaselineState = "frozen"
)

type ResultState string

const (
	ResultInsufficientBaseline ResultState = "insufficient_baseline"
	ResultInsufficientCurrent  ResultState = "insufficient_current_data"
	ResultReady                ResultState = "ready"
)

type OperationKey struct {
	Service   string
	Operation string
}

type Observation struct {
	Key       OperationKey
	Timestamp time.Time
	Latency   time.Duration
	Failed    bool
}

type BaselineOperation struct {
	Service          string  `json:"service"`
	Operation        string  `json:"operation"`
	Samples          int     `json:"samples"`
	Sufficient       bool    `json:"sufficient"`
	LatencyMedianMS  float64 `json:"latency_median_ms"`
	LatencyP95MS     float64 `json:"latency_p95_ms"`
	LogLatencyMedian float64 `json:"log_latency_median"`
	LogLatencyMAD    float64 `json:"log_latency_mad"`
	RobustScale      float64 `json:"robust_scale"`
	Errors           int     `json:"errors"`
	ErrorRate        float64 `json:"error_rate"`
}

type BaselineSnapshot struct {
	State      BaselineState       `json:"state"`
	Operations []BaselineOperation `json:"operations"`
}

type OperationResult struct {
	Service   string      `json:"service"`
	Operation string      `json:"operation"`
	State     ResultState `json:"state"`

	BaselineSamples int `json:"baseline_samples"`
	CurrentSamples  int `json:"current_samples"`

	BaselineLatencyMedianMS float64 `json:"baseline_latency_median_ms"`
	CurrentLatencyMedianMS  float64 `json:"current_latency_median_ms"`
	CurrentLatencyP95MS     float64 `json:"current_latency_p95_ms"`

	BaselineErrorRate float64 `json:"baseline_error_rate"`
	CurrentErrorRate  float64 `json:"current_error_rate"`

	LatencyZ float64 `json:"latency_z"`
	ErrorZ   float64 `json:"error_z"`

	LatencyAnomalous bool    `json:"latency_anomalous"`
	ErrorAnomalous   bool    `json:"error_anomalous"`
	Severity         float64 `json:"severity"`
}

type ServiceResult struct {
	Service   string  `json:"service"`
	Anomalous bool    `json:"anomalous"`
	Severity  float64 `json:"severity"`
}

type AnomalySnapshot struct {
	BaselineState BaselineState     `json:"baseline_state"`
	Services      []ServiceResult   `json:"services"`
	Operations    []OperationResult `json:"operations"`
}
