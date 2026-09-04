package anomaly

import (
	"errors"
	"math"
	"sort"
	"strings"
	"sync"
)

const (
	DefaultMinBaselineSamples = 30
	DefaultMaxBaselineSamples = 1000
	DefaultCurrentWindowSize  = 20
	DefaultMinCurrentSamples  = 10
	DefaultLatencyZThreshold  = 3.5
	DefaultErrorZThreshold    = 3.0
	DefaultScaleEpsilon       = 0.1
)

var ErrBaselineNotCollecting = errors.New("baseline is not collecting")

type Config struct {
	MinBaselineSamples int
	MaxBaselineSamples int
	CurrentWindowSize  int
	MinCurrentSamples  int
	LatencyZThreshold  float64
	ErrorZThreshold    float64
	ScaleEpsilon       float64
}

type Detector struct {
	mu sync.Mutex

	config Config
	state  BaselineState

	baselineSamples map[OperationKey][]Observation
	baseline        map[OperationKey]BaselineOperation
	current         map[OperationKey][]Observation
}

func NewDetector(config Config) (*Detector, error) {
	if config.MinBaselineSamples <= 0 {
		return nil, errors.New("minimum baseline samples must be greater than zero")
	}
	if config.MaxBaselineSamples < config.MinBaselineSamples {
		return nil, errors.New("maximum baseline samples must be at least the minimum")
	}
	if config.CurrentWindowSize <= 0 {
		return nil, errors.New("current window size must be greater than zero")
	}
	if config.MinCurrentSamples <= 0 || config.MinCurrentSamples > config.CurrentWindowSize {
		return nil, errors.New("minimum current samples must be between 1 and current window size")
	}
	if !positiveFinite(config.LatencyZThreshold) || !positiveFinite(config.ErrorZThreshold) ||
		!positiveFinite(config.ScaleEpsilon) {
		return nil, errors.New("thresholds and scale epsilon must be finite and greater than zero")
	}

	detector := &Detector{config: config}
	detector.resetAllLocked(StateEmpty)
	return detector, nil
}

func (detector *Detector) StartBaseline() {
	detector.mu.Lock()
	defer detector.mu.Unlock()
	detector.resetAllLocked(StateCollecting)
}

func (detector *Detector) FreezeBaseline() error {
	detector.mu.Lock()
	defer detector.mu.Unlock()
	if detector.state != StateCollecting {
		return ErrBaselineNotCollecting
	}

	detector.baseline = make(map[OperationKey]BaselineOperation, len(detector.baselineSamples))
	for key, observations := range detector.baselineSamples {
		detector.baseline[key] = detector.buildBaselineLocked(key, observations)
	}
	detector.current = make(map[OperationKey][]Observation)
	detector.state = StateFrozen
	return nil
}

func (detector *Detector) ResetCurrent() {
	detector.mu.Lock()
	defer detector.mu.Unlock()
	detector.current = make(map[OperationKey][]Observation)
}

func (detector *Detector) Observe(observation Observation) bool {
	observation.Key.Service = strings.TrimSpace(observation.Key.Service)
	observation.Key.Operation = strings.TrimSpace(observation.Key.Operation)
	if observation.Key.Service == "" || observation.Key.Operation == "" || observation.Latency < 0 {
		return false
	}

	detector.mu.Lock()
	defer detector.mu.Unlock()
	switch detector.state {
	case StateCollecting:
		detector.baselineSamples[observation.Key] = appendBounded(
			detector.baselineSamples[observation.Key], observation, detector.config.MaxBaselineSamples,
		)
		return true
	case StateFrozen:
		detector.current[observation.Key] = appendBounded(
			detector.current[observation.Key], observation, detector.config.CurrentWindowSize,
		)
		return true
	default:
		return false
	}
}

func (detector *Detector) Baseline() BaselineSnapshot {
	detector.mu.Lock()
	defer detector.mu.Unlock()

	operations := make([]BaselineOperation, 0)
	if detector.state == StateCollecting {
		operations = make([]BaselineOperation, 0, len(detector.baselineSamples))
		for key, observations := range detector.baselineSamples {
			operations = append(operations, detector.buildBaselineLocked(key, observations))
		}
	} else {
		operations = make([]BaselineOperation, 0, len(detector.baseline))
		for _, baseline := range detector.baseline {
			operations = append(operations, baseline)
		}
	}
	sortBaselineOperations(operations)
	return BaselineSnapshot{State: detector.state, Operations: operations}
}

func (detector *Detector) Anomalies() AnomalySnapshot {
	detector.mu.Lock()
	defer detector.mu.Unlock()
	return detector.anomaliesLocked()
}

func (detector *Detector) AnalysisSnapshot() AnalysisSnapshot {
	detector.mu.Lock()
	defer detector.mu.Unlock()

	refs := make([]SampleRef, 0)
	for key, observations := range detector.current {
		for _, observation := range observations {
			refs = append(refs, SampleRef{
				Key:       key,
				TraceID:   observation.TraceID,
				SpanID:    observation.SpanID,
				Timestamp: observation.Timestamp,
			})
		}
	}
	sort.Slice(refs, func(left, right int) bool {
		if refs[left].Key.Service != refs[right].Key.Service {
			return refs[left].Key.Service < refs[right].Key.Service
		}
		if refs[left].Key.Operation != refs[right].Key.Operation {
			return refs[left].Key.Operation < refs[right].Key.Operation
		}
		if !refs[left].Timestamp.Equal(refs[right].Timestamp) {
			return refs[left].Timestamp.Before(refs[right].Timestamp)
		}
		if refs[left].TraceID != refs[right].TraceID {
			return refs[left].TraceID < refs[right].TraceID
		}
		return refs[left].SpanID < refs[right].SpanID
	})
	return AnalysisSnapshot{
		Config:         detector.config,
		Anomalies:      detector.anomaliesLocked(),
		CurrentSamples: refs,
	}
}

func (detector *Detector) anomaliesLocked() AnomalySnapshot {

	keys := make(map[OperationKey]struct{}, len(detector.baseline)+len(detector.current))
	for key := range detector.baseline {
		keys[key] = struct{}{}
	}
	for key := range detector.current {
		keys[key] = struct{}{}
	}

	operations := make([]OperationResult, 0, len(keys))
	services := make(map[string]ServiceResult)
	for key := range keys {
		result := detector.operationResultLocked(key)
		operations = append(operations, result)
		service := services[key.Service]
		service.Service = key.Service
		if result.Severity > service.Severity {
			service.Severity = result.Severity
		}
		service.Anomalous = service.Anomalous || result.LatencyAnomalous || result.ErrorAnomalous
		services[key.Service] = service
	}
	sort.Slice(operations, func(left, right int) bool {
		if operations[left].Service != operations[right].Service {
			return operations[left].Service < operations[right].Service
		}
		return operations[left].Operation < operations[right].Operation
	})

	serviceResults := make([]ServiceResult, 0, len(services))
	for _, service := range services {
		serviceResults = append(serviceResults, service)
	}
	sort.Slice(serviceResults, func(left, right int) bool {
		return serviceResults[left].Service < serviceResults[right].Service
	})

	return AnomalySnapshot{
		BaselineState: detector.state,
		Services:      serviceResults,
		Operations:    operations,
	}
}

func (detector *Detector) operationResultLocked(key OperationKey) OperationResult {
	baseline, exists := detector.baseline[key]
	current := detector.current[key]
	result := OperationResult{
		Service:                 key.Service,
		Operation:               key.Operation,
		State:                   ResultInsufficientBaseline,
		BaselineSamples:         baseline.Samples,
		CurrentSamples:          len(current),
		BaselineLatencyMedianMS: baseline.LatencyMedianMS,
		BaselineErrorRate:       baseline.ErrorRate,
	}
	currentStats := calculateLatencyStats(current, detector.config.ScaleEpsilon)
	result.CurrentLatencyMedianMS = currentStats.rawMedian
	result.CurrentLatencyP95MS = currentStats.rawP95
	result.CurrentErrorRate = rawErrorRate(current)

	if detector.state != StateFrozen || !exists || !baseline.Sufficient {
		return result
	}
	if len(current) < detector.config.MinCurrentSamples {
		result.State = ResultInsufficientCurrent
		return result
	}

	result.State = ResultReady
	result.LatencyZ = math.Max(0, (currentStats.logMedian-baseline.LogLatencyMedian)/baseline.RobustScale)
	result.ErrorZ = errorRateZ(baseline.Errors, baseline.Samples, countErrors(current), len(current))
	result.LatencyAnomalous = result.LatencyZ >= detector.config.LatencyZThreshold
	result.ErrorAnomalous = result.ErrorZ >= detector.config.ErrorZThreshold
	result.Severity = math.Max(
		result.LatencyZ/detector.config.LatencyZThreshold,
		result.ErrorZ/detector.config.ErrorZThreshold,
	)
	return result
}

func (detector *Detector) buildBaselineLocked(key OperationKey, observations []Observation) BaselineOperation {
	stats := calculateLatencyStats(observations, detector.config.ScaleEpsilon)
	errorsCount := countErrors(observations)
	return BaselineOperation{
		Service:          key.Service,
		Operation:        key.Operation,
		Samples:          len(observations),
		Sufficient:       len(observations) >= detector.config.MinBaselineSamples,
		LatencyMedianMS:  stats.rawMedian,
		LatencyP95MS:     stats.rawP95,
		LogLatencyMedian: stats.logMedian,
		LogLatencyMAD:    stats.logMAD,
		RobustScale:      stats.scale,
		Errors:           errorsCount,
		ErrorRate:        smoothedBaselineErrorRate(errorsCount, len(observations)),
	}
}

func (detector *Detector) resetAllLocked(state BaselineState) {
	detector.state = state
	detector.baselineSamples = make(map[OperationKey][]Observation)
	detector.baseline = make(map[OperationKey]BaselineOperation)
	detector.current = make(map[OperationKey][]Observation)
}

func appendBounded(values []Observation, value Observation, limit int) []Observation {
	if len(values) < limit {
		return append(values, value)
	}
	copy(values, values[1:])
	values[len(values)-1] = value
	return values
}

func countErrors(observations []Observation) int {
	count := 0
	for _, observation := range observations {
		if observation.Failed {
			count++
		}
	}
	return count
}

func rawErrorRate(observations []Observation) float64 {
	if len(observations) == 0 {
		return 0
	}
	return float64(countErrors(observations)) / float64(len(observations))
}

func sortBaselineOperations(operations []BaselineOperation) {
	sort.Slice(operations, func(left, right int) bool {
		if operations[left].Service != operations[right].Service {
			return operations[left].Service < operations[right].Service
		}
		return operations[left].Operation < operations[right].Operation
	})
}

func positiveFinite(value float64) bool {
	return value > 0 && !math.IsNaN(value) && !math.IsInf(value, 0)
}
