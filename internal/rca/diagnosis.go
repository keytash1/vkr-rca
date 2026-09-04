package rca

import (
	"errors"
	"sort"

	"vkr-rca/internal/anomaly"
	"vkr-rca/internal/diagnosis"
	"vkr-rca/internal/graph"
)

type DiagnosisProvider struct {
	store             *graph.Store
	detector          *anomaly.Detector
	rankers           []diagnosis.Ranker
	minActiveCoverage float64
}

func NewDiagnosisProvider(
	store *graph.Store,
	detector *anomaly.Detector,
	minActiveCoverage float64,
) (*DiagnosisProvider, error) {
	if store == nil || detector == nil {
		return nil, errors.New("graph store and anomaly detector are required")
	}
	if minActiveCoverage <= 0 || minActiveCoverage > 1 {
		return nil, errors.New("minimum active topology trace coverage must be between 0 and 1")
	}
	return &DiagnosisProvider{
		store:             store,
		detector:          detector,
		rankers:           diagnosis.DefaultRankers(),
		minActiveCoverage: minActiveCoverage,
	}, nil
}

func (provider *DiagnosisProvider) Features() diagnosis.FeatureSnapshot {
	graphSnapshot := provider.store.Snapshot()
	analysis := provider.detector.AnalysisSnapshot()

	traceIDs := make([]string, 0, len(analysis.CurrentSamples))
	refsByOperation := make(map[anomaly.OperationKey][]diagnosis.SampleRef)
	for _, ref := range analysis.CurrentSamples {
		traceIDs = append(traceIDs, ref.TraceID)
		refsByOperation[ref.Key] = append(refsByOperation[ref.Key], diagnosis.SampleRef{
			Service:   ref.Key.Service,
			Operation: ref.Key.Operation,
			TraceID:   ref.TraceID,
			SpanID:    ref.SpanID,
			Timestamp: ref.Timestamp,
		})
	}
	retainedTraces := provider.store.Traces(traceIDs)
	traces := make(map[string][]diagnosis.TraceSpan, len(retainedTraces))
	for traceID, spans := range retainedTraces {
		converted := make([]diagnosis.TraceSpan, 0, len(spans))
		for _, span := range spans {
			converted = append(converted, diagnosis.TraceSpan{
				TraceID:      span.TraceID,
				SpanID:       span.SpanID,
				ParentSpanID: span.ParentSpanID,
				Service:      span.ServiceName,
				Kind:         diagnosisSpanKind(span.Kind),
				StartTime:    span.StartTime,
				EndTime:      span.EndTime,
			})
		}
		traces[traceID] = converted
	}

	services := make([]string, 0, len(graphSnapshot.Nodes))
	for _, node := range graphSnapshot.Nodes {
		services = append(services, node.Service)
	}
	edges := make([]diagnosis.Edge, 0, len(graphSnapshot.Edges))
	for _, edge := range graphSnapshot.Edges {
		edges = append(edges, diagnosis.Edge{Caller: edge.Source, Callee: edge.Target})
	}
	operations := make([]diagnosis.OperationEvidence, 0, len(analysis.Anomalies.Operations))
	for _, operation := range analysis.Anomalies.Operations {
		key := anomaly.OperationKey{Service: operation.Service, Operation: operation.Operation}
		operations = append(operations, diagnosis.OperationEvidence{
			Service:          operation.Service,
			Operation:        operation.Operation,
			Ready:            operation.State == anomaly.ResultReady,
			CurrentSamples:   operation.CurrentSamples,
			LatencyZ:         operation.LatencyZ,
			ErrorZ:           operation.ErrorZ,
			LatencyAnomalous: operation.LatencyAnomalous,
			ErrorAnomalous:   operation.ErrorAnomalous,
			M5Severity:       operation.Severity,
			SampleRefs:       refsByOperation[key],
		})
	}
	sort.Strings(services)
	return diagnosis.BuildFeatures(diagnosis.Input{
		BaselineState:                  string(analysis.Anomalies.BaselineState),
		LatencyThreshold:               analysis.Config.LatencyZThreshold,
		ErrorThreshold:                 analysis.Config.ErrorZThreshold,
		MinActiveTopologyTraceCoverage: provider.minActiveCoverage,
		Services:                       services,
		Edges:                          edges,
		Operations:                     operations,
		Traces:                         traces,
	})
}

func (provider *DiagnosisProvider) RCA() diagnosis.RCASnapshot {
	return diagnosis.BuildRCA(provider.Features(), provider.rankers)
}

func diagnosisSpanKind(kind graph.SpanKind) diagnosis.SpanKind {
	switch kind {
	case graph.SpanKindServer:
		return diagnosis.SpanKindServer
	case graph.SpanKindClient:
		return diagnosis.SpanKindClient
	case graph.SpanKindInternal:
		return diagnosis.SpanKindInternal
	default:
		return diagnosis.SpanKindOther
	}
}
