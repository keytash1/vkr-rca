package anomaly

import (
	"math"
	"sync"
	"testing"
	"time"
)

func TestBaselineLifecycleAndStatistics(t *testing.T) {
	detector := newTestDetector(t)
	if got := detector.Baseline(); got.State != StateEmpty || len(got.Operations) != 0 {
		t.Fatalf("empty baseline = %+v", got)
	}

	detector.StartBaseline()
	for _, latency := range []time.Duration{time.Millisecond, 2 * time.Millisecond, 3 * time.Millisecond, 4 * time.Millisecond, 5 * time.Millisecond} {
		detector.Observe(testObservation("payment", "GET /authorize", latency, false))
	}
	collecting := detector.Baseline()
	if collecting.State != StateCollecting || collecting.Operations[0].Samples != 5 {
		t.Fatalf("collecting baseline = %+v", collecting)
	}
	if got := detector.Anomalies(); got.BaselineState != StateCollecting || len(got.Operations) != 0 {
		t.Fatalf("classified before freeze: %+v", got)
	}

	if err := detector.FreezeBaseline(); err != nil {
		t.Fatalf("freeze: %v", err)
	}
	frozen := detector.Baseline()
	operation := frozen.Operations[0]
	if frozen.State != StateFrozen || !operation.Sufficient || operation.LatencyMedianMS != 3 {
		t.Fatalf("frozen baseline = %+v", frozen)
	}
	wantLogMedian := math.Log1p(3)
	if math.Abs(operation.LogLatencyMedian-wantLogMedian) > 1e-12 {
		t.Fatalf("log median = %v, want %v", operation.LogLatencyMedian, wantLogMedian)
	}
	wantMAD := median([]float64{
		math.Abs(math.Log1p(1) - wantLogMedian),
		math.Abs(math.Log1p(2) - wantLogMedian),
		0,
		math.Abs(math.Log1p(4) - wantLogMedian),
		math.Abs(math.Log1p(5) - wantLogMedian),
	})
	if math.Abs(operation.LogLatencyMAD-wantMAD) > 1e-12 {
		t.Fatalf("MAD = %v, want %v", operation.LogLatencyMAD, wantMAD)
	}
}

func TestZeroMADUsesEpsilonAndFrozenBaselineIsImmutable(t *testing.T) {
	detector := newTestDetector(t)
	collectBaseline(t, detector, 5, 10*time.Millisecond, false)
	before := detector.Baseline().Operations[0]
	if before.RobustScale != testConfig().ScaleEpsilon {
		t.Fatalf("scale = %v, want epsilon %v", before.RobustScale, testConfig().ScaleEpsilon)
	}

	for index := 0; index < 20; index++ {
		detector.Observe(testObservation("payment", "GET /authorize", 700*time.Millisecond, false))
	}
	after := detector.Baseline().Operations[0]
	if after != before {
		t.Fatalf("frozen baseline changed: before=%+v after=%+v", before, after)
	}

	detector.StartBaseline()
	if baseline := detector.Baseline(); baseline.State != StateCollecting || len(baseline.Operations) != 0 {
		t.Fatalf("new calibration did not reset baseline: %+v", baseline)
	}
}

func TestCannotFreezeOutsideCollecting(t *testing.T) {
	detector := newTestDetector(t)
	if err := detector.FreezeBaseline(); err != ErrBaselineNotCollecting {
		t.Fatalf("freeze error = %v", err)
	}
}

func TestInsufficientBaselineAndCurrentData(t *testing.T) {
	detector := newTestDetector(t)
	collectBaseline(t, detector, 4, 10*time.Millisecond, false)
	for index := 0; index < 10; index++ {
		detector.Observe(testObservation("payment", "GET /authorize", 700*time.Millisecond, false))
	}
	result := operationResult(t, detector)
	if result.State != ResultInsufficientBaseline || result.LatencyAnomalous {
		t.Fatalf("insufficient baseline result = %+v", result)
	}

	detector.StartBaseline()
	for index := 0; index < 5; index++ {
		detector.Observe(testObservation("payment", "GET /authorize", 10*time.Millisecond, false))
	}
	if err := detector.FreezeBaseline(); err != nil {
		t.Fatalf("freeze: %v", err)
	}
	for index := 0; index < 9; index++ {
		detector.Observe(testObservation("payment", "GET /authorize", 700*time.Millisecond, false))
	}
	result = operationResult(t, detector)
	if result.State != ResultInsufficientCurrent || result.LatencyAnomalous {
		t.Fatalf("insufficient current result = %+v", result)
	}
}

func TestLatencyDetectionHealthySustainedSpikeAndLower(t *testing.T) {
	tests := []struct {
		name      string
		current   []time.Duration
		anomalous bool
	}{
		{name: "healthy", current: repeatedLatency(20, 8*time.Millisecond), anomalous: false},
		{name: "sustained degradation", current: repeatedLatency(20, 700*time.Millisecond), anomalous: true},
		{name: "single spike", current: append(repeatedLatency(19, 8*time.Millisecond), 10*time.Second), anomalous: false},
		{name: "lower latency", current: repeatedLatency(20, time.Millisecond), anomalous: false},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			detector := newTestDetector(t)
			collectBaseline(t, detector, 50, 8*time.Millisecond, false)
			for _, latency := range test.current {
				detector.Observe(testObservation("payment", "GET /authorize", latency, false))
			}
			result := operationResult(t, detector)
			if result.LatencyAnomalous != test.anomalous {
				t.Fatalf("result = %+v", result)
			}
			if test.name == "lower latency" && result.LatencyZ != 0 {
				t.Fatalf("lower latency z = %v, want 0", result.LatencyZ)
			}
			if test.name == "single spike" && (result.LatencyZ != 0 || result.Severity != 0) {
				t.Fatalf("single spike result = %+v, want zero sustained score", result)
			}
			wantSeverity := math.Max(result.LatencyZ/testConfig().LatencyZThreshold, result.ErrorZ/testConfig().ErrorZThreshold)
			if result.Severity != wantSeverity {
				t.Fatalf("severity = %v, want %v", result.Severity, wantSeverity)
			}
			if math.IsNaN(result.Severity) || math.IsInf(result.Severity, 0) {
				t.Fatalf("non-finite result = %+v", result)
			}
		})
	}
}

func TestErrorRateDetectionAndThresholdBoundary(t *testing.T) {
	tests := []struct {
		name          string
		currentErrors int
		anomalous     bool
	}{
		{name: "zero current errors", currentErrors: 0, anomalous: false},
		{name: "moderate increase", currentErrors: 5, anomalous: true},
		{name: "all current errors", currentErrors: 20, anomalous: true},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			detector := newTestDetector(t)
			collectBaseline(t, detector, 50, 8*time.Millisecond, false)
			observeErrors(detector, 20, test.currentErrors)
			result := operationResult(t, detector)
			if result.ErrorAnomalous != test.anomalous {
				t.Fatalf("result = %+v", result)
			}
			if math.IsNaN(result.ErrorZ) || math.IsInf(result.ErrorZ, 0) {
				t.Fatalf("error z is not finite: %+v", result)
			}
		})
	}

	boundary := errorRateZ(0, 50, 5, 20)
	config := testConfig()
	config.ErrorZThreshold = boundary
	detector, err := NewDetector(config)
	if err != nil {
		t.Fatalf("new detector: %v", err)
	}
	collectBaseline(t, detector, 50, 8*time.Millisecond, false)
	observeErrors(detector, 20, 5)
	result := operationResult(t, detector)
	if !result.ErrorAnomalous || result.ErrorZ != boundary {
		t.Fatalf("threshold boundary result = %+v, threshold=%v", result, boundary)
	}
}

func TestCurrentWindowIsBoundedAndResetPreservesBaseline(t *testing.T) {
	detector := newTestDetector(t)
	collectBaseline(t, detector, 50, 8*time.Millisecond, false)
	observeErrors(detector, 5, 5)
	observeErrors(detector, 20, 0)
	result := operationResult(t, detector)
	if result.CurrentSamples != 20 || result.CurrentErrorRate != 0 {
		t.Fatalf("bounded window result = %+v", result)
	}

	detector.ResetCurrent()
	result = operationResult(t, detector)
	if result.State != ResultInsufficientCurrent || result.CurrentSamples != 0 || result.BaselineSamples != 50 {
		t.Fatalf("reset result = %+v", result)
	}
}

func TestBaselineWindowIsBounded(t *testing.T) {
	detector := newTestDetector(t)
	detector.StartBaseline()
	for index := 0; index < 105; index++ {
		detector.Observe(testObservation("payment", "GET /authorize", time.Duration(index+1)*time.Millisecond, false))
	}
	if err := detector.FreezeBaseline(); err != nil {
		t.Fatalf("freeze: %v", err)
	}
	baseline := detector.Baseline().Operations[0]
	if baseline.Samples != testConfig().MaxBaselineSamples {
		t.Fatalf("baseline samples = %d, want %d", baseline.Samples, testConfig().MaxBaselineSamples)
	}
	if baseline.LatencyMedianMS != 55.5 {
		t.Fatalf("bounded baseline median = %v, want 55.5", baseline.LatencyMedianMS)
	}
}

func TestOperationAndServiceAggregationIsDeterministic(t *testing.T) {
	detector := newTestDetector(t)
	detector.StartBaseline()
	for index := 0; index < 5; index++ {
		detector.Observe(testObservation("payment", "GET /refund", 8*time.Millisecond, false))
		detector.Observe(testObservation("gateway", "GET /api/order", 8*time.Millisecond, false))
		detector.Observe(testObservation("payment", "GET /authorize", 8*time.Millisecond, false))
	}
	if err := detector.FreezeBaseline(); err != nil {
		t.Fatalf("freeze: %v", err)
	}
	for index := 0; index < 20; index++ {
		detector.Observe(testObservation("payment", "GET /refund", 8*time.Millisecond, false))
		detector.Observe(testObservation("gateway", "GET /api/order", 8*time.Millisecond, false))
		detector.Observe(testObservation("payment", "GET /authorize", 700*time.Millisecond, false))
	}

	snapshot := detector.Anomalies()
	if len(snapshot.Services) != 2 || snapshot.Services[0].Service != "gateway" || snapshot.Services[1].Service != "payment" {
		t.Fatalf("services ordering = %+v", snapshot.Services)
	}
	if len(snapshot.Operations) != 3 || snapshot.Operations[1].Operation != "GET /authorize" || snapshot.Operations[2].Operation != "GET /refund" {
		t.Fatalf("operations ordering = %+v", snapshot.Operations)
	}
	if !snapshot.Services[1].Anomalous || snapshot.Services[1].Severity != snapshot.Operations[1].Severity {
		t.Fatalf("service summary = %+v operations=%+v", snapshot.Services[1], snapshot.Operations)
	}
}

func TestConcurrentObserveAndSnapshots(t *testing.T) {
	detector := newTestDetector(t)
	collectBaseline(t, detector, 50, 8*time.Millisecond, false)
	var waitGroup sync.WaitGroup
	for worker := 0; worker < 10; worker++ {
		waitGroup.Add(1)
		go func(worker int) {
			defer waitGroup.Done()
			for index := 0; index < 100; index++ {
				detector.Observe(testObservation("service", "operation", time.Duration(worker+1)*time.Millisecond, index%3 == 0))
				_ = detector.Anomalies()
				_ = detector.Baseline()
			}
		}(worker)
	}
	waitGroup.Wait()
}

func TestInvalidConfigurationAndObservation(t *testing.T) {
	invalid := []Config{
		{},
		{MinBaselineSamples: 2, MaxBaselineSamples: 1, CurrentWindowSize: 1, MinCurrentSamples: 1, LatencyZThreshold: 1, ErrorZThreshold: 1, ScaleEpsilon: 1},
		{MinBaselineSamples: 1, MaxBaselineSamples: 1, CurrentWindowSize: 1, MinCurrentSamples: 2, LatencyZThreshold: 1, ErrorZThreshold: 1, ScaleEpsilon: 1},
	}
	for _, config := range invalid {
		if _, err := NewDetector(config); err == nil {
			t.Fatalf("NewDetector(%+v) returned no error", config)
		}
	}
	detector := newTestDetector(t)
	detector.StartBaseline()
	if detector.Observe(Observation{Key: OperationKey{Service: "", Operation: "op"}}) {
		t.Fatal("invalid observation was accepted")
	}
}

func newTestDetector(t *testing.T) *Detector {
	t.Helper()
	detector, err := NewDetector(testConfig())
	if err != nil {
		t.Fatalf("new detector: %v", err)
	}
	return detector
}

func testConfig() Config {
	return Config{
		MinBaselineSamples: 5,
		MaxBaselineSamples: 100,
		CurrentWindowSize:  20,
		MinCurrentSamples:  10,
		LatencyZThreshold:  3.5,
		ErrorZThreshold:    3.0,
		ScaleEpsilon:       0.1,
	}
}

func collectBaseline(t *testing.T, detector *Detector, samples int, latency time.Duration, failed bool) {
	t.Helper()
	detector.StartBaseline()
	for index := 0; index < samples; index++ {
		detector.Observe(testObservation("payment", "GET /authorize", latency, failed))
	}
	if err := detector.FreezeBaseline(); err != nil {
		t.Fatalf("freeze: %v", err)
	}
}

func observeErrors(detector *Detector, samples, errors int) {
	for index := 0; index < samples; index++ {
		detector.Observe(testObservation("payment", "GET /authorize", 8*time.Millisecond, index < errors))
	}
}

func testObservation(service, operation string, latency time.Duration, failed bool) Observation {
	return Observation{
		Key:       OperationKey{Service: service, Operation: operation},
		Timestamp: time.Date(2026, 9, 4, 0, 0, 0, 0, time.UTC),
		Latency:   latency,
		Failed:    failed,
	}
}

func operationResult(t *testing.T, detector *Detector) OperationResult {
	t.Helper()
	snapshot := detector.Anomalies()
	if len(snapshot.Operations) != 1 {
		t.Fatalf("operations = %+v, want one", snapshot.Operations)
	}
	return snapshot.Operations[0]
}

func repeatedLatency(count int, latency time.Duration) []time.Duration {
	values := make([]time.Duration, count)
	for index := range values {
		values[index] = latency
	}
	return values
}
