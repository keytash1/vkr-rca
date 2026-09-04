package externalrca

import (
	"errors"
	"sort"
	"strings"
	"time"

	"vkr-rca/internal/anomaly"
	"vkr-rca/internal/diagnosis"
)

const ProtocolVersion = "m8b-v1"

type Mode string

const (
	ModeFault   Mode = "fault"
	ModeHealthy Mode = "healthy"
)

type Span struct {
	TraceID      string `json:"trace_id"`
	SpanID       string `json:"span_id"`
	ParentSpanID string `json:"parent_span_id,omitempty"`
	Service      string `json:"service"`
	Operation    string `json:"operation"`
	StartUnixUS  int64  `json:"start_unix_us"`
	DurationUS   int64  `json:"duration_us"`
	StatusCode   *int64 `json:"status_code,omitempty"`
}

type Input struct {
	ExternalCaseID string `json:"external_case_id"`
	InjectUnix     int64  `json:"inject_unix"`
	Mode           Mode   `json:"mode"`
	Spans          []Span `json:"spans"`
}

type Coverage struct {
	InputSpans             int     `json:"input_spans"`
	WindowSpans            int     `json:"window_spans"`
	ServerSpans            int     `json:"server_spans"`
	ClientSpans            int     `json:"client_spans"`
	InternalSpans          int     `json:"internal_spans"`
	KindInferred           bool    `json:"kind_inferred"`
	ParentMatchRate        float64 `json:"parent_match_rate"`
	ErrorEvidenceCoverage  float64 `json:"error_evidence_coverage"`
	ExclusiveTraceCoverage float64 `json:"exclusive_trace_coverage"`
}

type Output struct {
	ProtocolVersion string                    `json:"protocol_version"`
	ExternalCaseID  string                    `json:"external_case_id"`
	Mode            Mode                      `json:"mode"`
	Baseline        anomaly.BaselineSnapshot  `json:"baseline"`
	Anomalies       anomaly.AnomalySnapshot   `json:"anomalies"`
	Features        diagnosis.FeatureSnapshot `json:"features"`
	RCA             diagnosis.RCASnapshot     `json:"rca"`
	Coverage        Coverage                  `json:"coverage"`
}

type inferredSpan struct {
	Span
	kind diagnosis.SpanKind
}

func Process(input Input) (Output, error) {
	if strings.TrimSpace(input.ExternalCaseID) == "" || input.InjectUnix <= 0 {
		return Output{}, errors.New("external case ID and injection time are required")
	}
	if input.Mode != ModeFault && input.Mode != ModeHealthy {
		return Output{}, errors.New("mode must be fault or healthy")
	}
	spans := validSortedSpans(input.Spans)
	if len(spans) == 0 {
		return Output{}, errors.New("no valid spans")
	}
	inferred, coverage := inferKinds(spans)
	baselineStart, baselineEnd, currentStart, currentEnd := windows(input.InjectUnix, input.Mode)

	detector, err := anomaly.NewDetector(anomaly.Config{
		MinBaselineSamples: anomaly.DefaultMinBaselineSamples,
		MaxBaselineSamples: anomaly.DefaultMaxBaselineSamples,
		CurrentWindowSize:  anomaly.DefaultCurrentWindowSize,
		MinCurrentSamples:  anomaly.DefaultMinCurrentSamples,
		LatencyZThreshold:  anomaly.DefaultLatencyZThreshold,
		ErrorZThreshold:    anomaly.DefaultErrorZThreshold,
		ScaleEpsilon:       anomaly.DefaultScaleEpsilon,
	})
	if err != nil {
		return Output{}, err
	}
	detector.StartBaseline()
	for _, span := range inferred {
		if span.kind == diagnosis.SpanKindServer && inWindow(span.StartUnixUS, baselineStart, baselineEnd) {
			detector.Observe(observation(span))
		}
	}
	if err := detector.FreezeBaseline(); err != nil {
		return Output{}, err
	}
	for _, span := range inferred {
		if span.kind == diagnosis.SpanKindServer && inWindow(span.StartUnixUS, currentStart, currentEnd) {
			detector.Observe(observation(span))
		}
	}

	analysis := detector.AnalysisSnapshot()
	traceMap := make(map[string][]diagnosis.TraceSpan)
	edges := make([]diagnosis.Edge, 0)
	windowSpans := 0
	statusKnown := 0
	serverCurrent := 0
	for _, span := range inferred {
		if !inWindow(span.StartUnixUS, baselineStart, currentEnd) {
			continue
		}
		windowSpans++
		if span.kind == diagnosis.SpanKindServer && inWindow(span.StartUnixUS, currentStart, currentEnd) {
			serverCurrent++
			if span.StatusCode != nil {
				statusKnown++
			}
		}
		traceMap[span.TraceID] = append(traceMap[span.TraceID], diagnosis.TraceSpan{
			TraceID: span.TraceID, SpanID: span.SpanID, ParentSpanID: span.ParentSpanID,
			Service: span.Service, Kind: span.kind, StartTime: unixUS(span.StartUnixUS),
			EndTime: unixUS(span.StartUnixUS + span.DurationUS),
		})
	}
	for _, trace := range traceMap {
		byID := make(map[string]diagnosis.TraceSpan, len(trace))
		for _, span := range trace {
			byID[span.SpanID] = span
		}
		for _, child := range trace {
			if parent, ok := byID[child.ParentSpanID]; ok && parent.Service != child.Service {
				edges = append(edges, diagnosis.Edge{Caller: parent.Service, Callee: child.Service})
			}
		}
	}

	refsByKey := make(map[anomaly.OperationKey][]diagnosis.SampleRef)
	for _, ref := range analysis.CurrentSamples {
		refsByKey[ref.Key] = append(refsByKey[ref.Key], diagnosis.SampleRef{
			Service: ref.Key.Service, Operation: ref.Key.Operation,
			TraceID: ref.TraceID, SpanID: ref.SpanID, Timestamp: ref.Timestamp,
		})
	}
	operations := make([]diagnosis.OperationEvidence, 0, len(analysis.Anomalies.Operations))
	services := make(map[string]struct{})
	for _, operation := range analysis.Anomalies.Operations {
		services[operation.Service] = struct{}{}
		operations = append(operations, diagnosis.OperationEvidence{
			Service: operation.Service, Operation: operation.Operation,
			Ready: operation.State == anomaly.ResultReady, CurrentSamples: operation.CurrentSamples,
			LatencyZ: operation.LatencyZ, ErrorZ: operation.ErrorZ,
			LatencyAnomalous: operation.LatencyAnomalous, ErrorAnomalous: operation.ErrorAnomalous,
			M5Severity: operation.Severity,
			SampleRefs: refsByKey[anomaly.OperationKey{Service: operation.Service, Operation: operation.Operation}],
		})
	}
	serviceNames := make([]string, 0, len(services))
	for service := range services {
		serviceNames = append(serviceNames, service)
	}
	sort.Strings(serviceNames)
	features := diagnosis.BuildFeatures(diagnosis.Input{
		BaselineState:    string(analysis.Anomalies.BaselineState),
		LatencyThreshold: anomaly.DefaultLatencyZThreshold, ErrorThreshold: anomaly.DefaultErrorZThreshold,
		MinActiveTopologyTraceCoverage: diagnosis.DefaultMinActiveTopologyTraceCoverage,
		Services:                       serviceNames, Edges: edges, Operations: operations, Traces: traceMap,
	})
	traceSamples, currentSamples := 0, 0
	for _, feature := range features.Services {
		traceSamples += feature.TraceSamples
		currentSamples += feature.CurrentSamples
	}
	coverage.WindowSpans = windowSpans
	if serverCurrent > 0 {
		coverage.ErrorEvidenceCoverage = float64(statusKnown) / float64(serverCurrent)
	}
	if currentSamples > 0 {
		coverage.ExclusiveTraceCoverage = float64(traceSamples) / float64(currentSamples)
	}
	return Output{
		ProtocolVersion: ProtocolVersion, ExternalCaseID: input.ExternalCaseID, Mode: input.Mode,
		Baseline: detector.Baseline(), Anomalies: analysis.Anomalies, Features: features,
		RCA: diagnosis.BuildRCA(features, diagnosis.DefaultRankers()), Coverage: coverage,
	}, nil
}

func validSortedSpans(values []Span) []Span {
	result := make([]Span, 0, len(values))
	for _, span := range values {
		span.TraceID, span.SpanID = strings.TrimSpace(span.TraceID), strings.TrimSpace(span.SpanID)
		span.ParentSpanID, span.Service = strings.TrimSpace(span.ParentSpanID), strings.TrimSpace(span.Service)
		span.Operation = strings.TrimSpace(span.Operation)
		if span.TraceID == "" || span.SpanID == "" || span.Service == "" || span.Operation == "" || span.StartUnixUS <= 0 || span.DurationUS < 0 {
			continue
		}
		result = append(result, span)
	}
	sort.Slice(result, func(i, j int) bool {
		if result[i].StartUnixUS != result[j].StartUnixUS {
			return result[i].StartUnixUS < result[j].StartUnixUS
		}
		return result[i].SpanID < result[j].SpanID
	})
	return result
}

func inferKinds(spans []Span) ([]inferredSpan, Coverage) {
	byTrace := make(map[string]map[string]Span)
	children := make(map[string]map[string][]Span)
	for _, span := range spans {
		if byTrace[span.TraceID] == nil {
			byTrace[span.TraceID] = make(map[string]Span)
			children[span.TraceID] = make(map[string][]Span)
		}
		byTrace[span.TraceID][span.SpanID] = span
		if span.ParentSpanID != "" {
			children[span.TraceID][span.ParentSpanID] = append(children[span.TraceID][span.ParentSpanID], span)
		}
	}
	coverage := Coverage{InputSpans: len(spans), KindInferred: true}
	parents, matches := 0, 0
	result := make([]inferredSpan, 0, len(spans))
	for _, span := range spans {
		kind := diagnosis.SpanKindInternal
		parent, parentFound := byTrace[span.TraceID][span.ParentSpanID]
		if span.ParentSpanID != "" {
			parents++
			if parentFound {
				matches++
			}
		}
		switch {
		case span.ParentSpanID == "" || (parentFound && parent.Service != span.Service):
			kind = diagnosis.SpanKindServer
		case hasCrossServiceChild(span, children[span.TraceID][span.SpanID]):
			kind = diagnosis.SpanKindClient
		}
		switch kind {
		case diagnosis.SpanKindServer:
			coverage.ServerSpans++
		case diagnosis.SpanKindClient:
			coverage.ClientSpans++
		default:
			coverage.InternalSpans++
		}
		result = append(result, inferredSpan{Span: span, kind: kind})
	}
	if parents > 0 {
		coverage.ParentMatchRate = float64(matches) / float64(parents)
	}
	return result, coverage
}

func hasCrossServiceChild(parent Span, children []Span) bool {
	for _, child := range children {
		if child.Service != parent.Service {
			return true
		}
	}
	return false
}

func windows(inject int64, mode Mode) (int64, int64, int64, int64) {
	value := inject * 1_000_000
	if mode == ModeHealthy {
		return value - 600_000_000, value - 300_000_000, value - 300_000_000, value
	}
	return value - 600_000_000, value, value, value + 600_000_000
}

func inWindow(value, start, end int64) bool { return value >= start && value < end }

func observation(span inferredSpan) anomaly.Observation {
	return anomaly.Observation{
		Key:     anomaly.OperationKey{Service: span.Service, Operation: span.Operation},
		TraceID: span.TraceID, SpanID: span.SpanID, Timestamp: unixUS(span.StartUnixUS),
		Latency: time.Duration(span.DurationUS) * time.Microsecond, Failed: failed(span.StatusCode),
	}
}

func failed(code *int64) bool {
	if code == nil || *code == 0 {
		return false
	}
	return (*code >= 1 && *code <= 16) || *code >= 400
}

func unixUS(value int64) time.Time { return time.Unix(0, value*int64(time.Microsecond)).UTC() }
