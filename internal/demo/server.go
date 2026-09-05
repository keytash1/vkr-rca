package demo

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"io/fs"
	"net/http"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"sync"
	"time"
)

type Config struct {
	Root             string
	OperationTimeout time.Duration
	Live             LiveConfig
}

type OperationState struct {
	State    string   `json:"state"`
	Scenario Scenario `json:"scenario,omitempty"`
	CaseID   string   `json:"case_id,omitempty"`
	Error    string   `json:"error,omitempty"`
}

type Server struct {
	config       Config
	live         *LiveClient
	freeze       FreezeStatus
	registry     ModelRegistry
	research     map[string]any
	architecture map[string]any

	mutation       sync.Mutex
	mu             sync.RWMutex
	liveState      OperationState
	replayState    OperationState
	lastLive       LiveResult
	lastPrediction map[string]any
}

type replayManifest struct {
	Version        string         `json:"version"`
	Source         map[string]any `json:"source"`
	Cases          []ReplayCase   `json:"cases"`
	TruthIsolation string         `json:"truth_isolation"`
}

type ReplayCase struct {
	ID                string         `json:"id"`
	Title             string         `json:"title"`
	Dataset           string         `json:"dataset"`
	System            string         `json:"system"`
	IncidentTimestamp int64          `json:"incident_timestamp"`
	CandidateCount    int            `json:"candidate_count"`
	Telemetry         map[string]any `json:"telemetry"`
	Model             map[string]any `json:"model"`
	PredictionSHA256  string         `json:"prediction_sha256"`
}

func NewServer(config Config) (*Server, error) {
	if config.Root == "" || config.OperationTimeout <= 0 {
		return nil, errors.New("demo root and operation timeout are required")
	}
	freeze, err := VerifyFrozen(config.Root)
	if err != nil {
		return nil, err
	}
	registry, err := LoadModelRegistry(config.Root)
	if err != nil {
		return nil, fmt.Errorf("load model registry: %w", err)
	}
	research, err := LoadResearch(config.Root, freeze, registry)
	if err != nil {
		return nil, fmt.Errorf("load research results: %w", err)
	}
	architecture, err := LoadArchitecture(config.Root)
	if err != nil {
		return nil, fmt.Errorf("load architecture: %w", err)
	}
	live, err := NewLiveClient(config.Live)
	if err != nil {
		return nil, err
	}
	return &Server{
		config: config, live: live, freeze: freeze, registry: registry,
		research: research, architecture: architecture,
		liveState:   OperationState{State: "idle", Scenario: ScenarioHealthy},
		replayState: OperationState{State: "idle"},
	}, nil
}

func (server *Server) Handler(static fs.FS) http.Handler {
	mux := http.NewServeMux()
	mux.HandleFunc("/api/demo/health", server.handleHealth)
	mux.HandleFunc("/api/demo/research", server.handleResearch)
	mux.HandleFunc("/api/demo/architecture", server.handleArchitecture)
	mux.HandleFunc("/api/demo/live/reset", server.handleLiveReset)
	mux.HandleFunc("/api/demo/live/scenario", server.handleLiveScenario)
	mux.HandleFunc("/api/demo/live/traffic", server.handleLiveTraffic)
	mux.HandleFunc("/api/demo/live/result", server.handleLiveResult)
	mux.HandleFunc("/api/demo/replay/cases", server.handleReplayCases)
	mux.HandleFunc("/api/demo/replay/analyze", server.handleReplayAnalyze)
	mux.HandleFunc("/api/demo/replay/reveal", server.handleReplayReveal)
	mux.Handle("/", http.FileServer(http.FS(static)))
	return http.TimeoutHandler(mux, server.config.OperationTimeout+5*time.Second, `{"error":"demo operation timed out"}`)
}

func (server *Server) handleHealth(writer http.ResponseWriter, request *http.Request) {
	if !method(writer, request, http.MethodGet) {
		return
	}
	server.mu.RLock()
	liveState, replayState := server.liveState, server.replayState
	server.mu.RUnlock()
	_, preparedErr := server.loadReplayManifest()
	writeJSON(writer, http.StatusOK, map[string]any{
		"service": "demo", "status": "ok", "research": "FROZEN_AT_M10A",
		"freeze": server.freeze, "live": liveState, "replay": replayState,
		"replay_prepared": preparedErr == nil,
	})
}

func (server *Server) handleResearch(writer http.ResponseWriter, request *http.Request) {
	if !method(writer, request, http.MethodGet) {
		return
	}
	writeJSON(writer, http.StatusOK, server.research)
}

func (server *Server) handleArchitecture(writer http.ResponseWriter, request *http.Request) {
	if !method(writer, request, http.MethodGet) {
		return
	}
	writeJSON(writer, http.StatusOK, server.architecture)
}

func (server *Server) handleLiveReset(writer http.ResponseWriter, request *http.Request) {
	if !method(writer, request, http.MethodPost) || !server.startMutation(writer, "live") {
		return
	}
	defer server.mutation.Unlock()
	server.setLiveState(OperationState{State: "running", Scenario: ScenarioHealthy})
	ctx, cancel := context.WithTimeout(request.Context(), server.config.OperationTimeout)
	defer cancel()
	if err := server.live.Reset(ctx); err != nil {
		server.failLive(writer, err)
		return
	}
	server.mu.Lock()
	server.lastLive = LiveResult{}
	server.liveState = OperationState{State: "idle", Scenario: ScenarioHealthy}
	state := server.liveState
	server.mu.Unlock()
	writeJSON(writer, http.StatusOK, state)
}

func (server *Server) handleLiveScenario(writer http.ResponseWriter, request *http.Request) {
	if !method(writer, request, http.MethodPost) || !server.startMutation(writer, "live") {
		return
	}
	defer server.mutation.Unlock()
	var body struct {
		Scenario string `json:"scenario"`
	}
	if err := decodeBody(request, &body); err != nil {
		writeJSON(writer, http.StatusBadRequest, map[string]string{"error": err.Error()})
		return
	}
	scenario, err := ParseScenario(body.Scenario)
	if err != nil {
		writeJSON(writer, http.StatusBadRequest, map[string]string{"error": err.Error()})
		return
	}
	server.setLiveState(OperationState{State: "running", Scenario: scenario})
	ctx, cancel := context.WithTimeout(request.Context(), server.config.OperationTimeout)
	defer cancel()
	if err := server.live.ApplyScenario(ctx, scenario); err != nil {
		server.failLive(writer, err)
		return
	}
	state := OperationState{State: "idle", Scenario: scenario}
	server.setLiveState(state)
	writeJSON(writer, http.StatusOK, state)
}

func (server *Server) handleLiveTraffic(writer http.ResponseWriter, request *http.Request) {
	if !method(writer, request, http.MethodPost) || !server.startMutation(writer, "live") {
		return
	}
	defer server.mutation.Unlock()
	var body struct {
		Requests int `json:"requests"`
	}
	if err := decodeBody(request, &body); err != nil {
		writeJSON(writer, http.StatusBadRequest, map[string]string{"error": err.Error()})
		return
	}
	if body.Requests == 0 {
		body.Requests = 20
	}
	server.mu.RLock()
	scenario := server.liveState.Scenario
	server.mu.RUnlock()
	server.setLiveState(OperationState{State: "running", Scenario: scenario})
	ctx, cancel := context.WithTimeout(request.Context(), server.config.OperationTimeout)
	defer cancel()
	traffic, err := server.live.GenerateTraffic(ctx, body.Requests)
	if err != nil {
		server.failLive(writer, err)
		return
	}
	server.setLiveState(OperationState{State: "analyzing", Scenario: scenario})
	result, err := server.live.Snapshot(ctx, scenario, traffic.TraceIDs)
	if err != nil {
		server.failLive(writer, err)
		return
	}
	server.mu.Lock()
	server.lastLive = result
	server.liveState = OperationState{State: "complete", Scenario: scenario}
	server.mu.Unlock()
	writeJSON(writer, http.StatusOK, map[string]any{"state": "complete", "traffic": traffic, "result": result})
}

func (server *Server) handleLiveResult(writer http.ResponseWriter, request *http.Request) {
	if !method(writer, request, http.MethodGet) {
		return
	}
	server.mu.RLock()
	defer server.mu.RUnlock()
	writeJSON(writer, http.StatusOK, map[string]any{"state": server.liveState, "result": server.lastLive})
}

func (server *Server) handleReplayCases(writer http.ResponseWriter, request *http.Request) {
	if !method(writer, request, http.MethodGet) {
		return
	}
	manifest, err := server.loadReplayManifest()
	if err != nil {
		writeJSON(writer, http.StatusServiceUnavailable, map[string]string{"error": "run make demo-prepare first: " + err.Error()})
		return
	}
	server.mu.RLock()
	state := server.replayState
	server.mu.RUnlock()
	writeJSON(writer, http.StatusOK, map[string]any{"version": manifest.Version, "source": manifest.Source,
		"cases": manifest.Cases, "truth_isolation": manifest.TruthIsolation, "state": state})
}

func (server *Server) handleReplayAnalyze(writer http.ResponseWriter, request *http.Request) {
	if !method(writer, request, http.MethodPost) || !server.startMutation(writer, "replay") {
		return
	}
	defer server.mutation.Unlock()
	var body struct {
		CaseID string `json:"case_id"`
	}
	if err := decodeBody(request, &body); err != nil {
		writeJSON(writer, http.StatusBadRequest, map[string]string{"error": err.Error()})
		return
	}
	manifest, err := server.loadReplayManifest()
	if err != nil {
		writeJSON(writer, http.StatusServiceUnavailable, map[string]string{"error": "run make demo-prepare first"})
		return
	}
	preparedCase, ok := manifest.caseByID(body.CaseID)
	if !ok {
		writeJSON(writer, http.StatusNotFound, map[string]string{"error": "unknown prepared case"})
		return
	}
	server.setReplayState(OperationState{State: "analyzing", CaseID: body.CaseID})
	predictionPath := server.replayPath(body.CaseID, "prediction.json")
	actualSHA256, err := fileSHA256(predictionPath)
	if err != nil {
		server.failReplay(writer, err)
		return
	}
	if actualSHA256 != preparedCase.PredictionSHA256 {
		server.failReplay(writer, errors.New("prepared prediction hash mismatch; rerun make demo-prepare"))
		return
	}
	var prediction map[string]any
	if err := readJSON(predictionPath, &prediction); err != nil {
		server.failReplay(writer, err)
		return
	}
	if err := validatePredictionJSON(prediction); err != nil {
		server.failReplay(writer, err)
		return
	}
	server.mu.Lock()
	server.lastPrediction = prediction
	server.replayState = OperationState{State: "complete", CaseID: body.CaseID}
	server.mu.Unlock()
	writeJSON(writer, http.StatusOK, map[string]any{"state": "complete", "prediction": prediction})
}

func (server *Server) handleReplayReveal(writer http.ResponseWriter, request *http.Request) {
	if !method(writer, request, http.MethodPost) || !server.startMutation(writer, "replay") {
		return
	}
	defer server.mutation.Unlock()
	var body struct {
		CaseID string `json:"case_id"`
	}
	if err := decodeBody(request, &body); err != nil {
		writeJSON(writer, http.StatusBadRequest, map[string]string{"error": err.Error()})
		return
	}
	server.mu.RLock()
	active := server.replayState.State == "complete" && server.replayState.CaseID == body.CaseID
	server.mu.RUnlock()
	if !active {
		writeJSON(writer, http.StatusConflict, map[string]string{"error": "analyze this case before revealing ground truth"})
		return
	}
	var truth map[string]any
	if err := readJSON(server.replayPath(body.CaseID, "truth.json"), &truth); err != nil {
		server.failReplay(writer, err)
		return
	}
	writeJSON(writer, http.StatusOK, map[string]any{"case_id": body.CaseID, "ground_truth": truth})
}

func (server *Server) startMutation(writer http.ResponseWriter, scope string) bool {
	if !server.mutation.TryLock() {
		writeJSON(writer, http.StatusConflict, map[string]string{"error": "another demo mutation is already running", "scope": scope})
		return false
	}
	return true
}

func (server *Server) setLiveState(state OperationState) {
	server.mu.Lock()
	server.liveState = state
	server.mu.Unlock()
}

func (server *Server) setReplayState(state OperationState) {
	server.mu.Lock()
	server.replayState = state
	server.mu.Unlock()
}

func (server *Server) failLive(writer http.ResponseWriter, err error) {
	state := OperationState{State: "error", Error: err.Error()}
	server.setLiveState(state)
	writeJSON(writer, statusForError(err), state)
}

func (server *Server) failReplay(writer http.ResponseWriter, err error) {
	state := OperationState{State: "error", Error: err.Error()}
	server.setReplayState(state)
	writeJSON(writer, statusForError(err), state)
}

func (server *Server) loadReplayManifest() (replayManifest, error) {
	var manifest replayManifest
	if err := readJSON(filepath.Join(server.config.Root, "demo-data/manifest.json"), &manifest); err != nil {
		return replayManifest{}, err
	}
	if len(manifest.Cases) < 8 {
		return replayManifest{}, errors.New("prepared replay manifest is incomplete")
	}
	return manifest, nil
}

func (manifest replayManifest) caseByID(caseID string) (ReplayCase, bool) {
	for _, value := range manifest.Cases {
		if value.ID == caseID {
			return value, true
		}
	}
	return ReplayCase{}, false
}

func (server *Server) replayPath(caseID, name string) string {
	return filepath.Join(server.config.Root, "demo-data/cases", filepath.Base(caseID), name)
}

func validatePredictionJSON(prediction map[string]any) error {
	forbidden := map[string]bool{"root": true, "root_service": true, "fault": true, "fault_family": true,
		"label": true, "truth": true, "ground_truth": true}
	var visit func(any) error
	visit = func(value any) error {
		switch typed := value.(type) {
		case map[string]any:
			for key, nested := range typed {
				if forbidden[key] {
					return fmt.Errorf("prediction contains forbidden ground-truth key %s", key)
				}
				if err := visit(nested); err != nil {
					return err
				}
			}
		case []any:
			for _, nested := range typed {
				if err := visit(nested); err != nil {
					return err
				}
			}
		}
		return nil
	}
	if err := visit(prediction); err != nil {
		return err
	}
	ranking, ok := prediction["ranking"].([]any)
	if !ok || len(ranking) == 0 {
		return errors.New("prediction ranking is empty")
	}
	previousScore := 0.0
	previousService := ""
	for index, raw := range ranking {
		entry, ok := raw.(map[string]any)
		if !ok {
			return errors.New("prediction ranking entry is not an object")
		}
		rank, rankOK := entry["rank"].(float64)
		score, scoreOK := entry["score"].(float64)
		service, serviceOK := entry["service"].(string)
		if !rankOK || !scoreOK || !serviceOK || service == "" || int(rank) != index+1 {
			return errors.New("prediction ranks are not contiguous")
		}
		if index > 0 && (score > previousScore || score == previousScore && service < previousService) {
			return errors.New("prediction order is not deterministic")
		}
		previousScore, previousService = score, service
	}
	return nil
}

func decodeBody(request *http.Request, destination any) error {
	decoder := json.NewDecoder(io.LimitReader(request.Body, 64<<10))
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(destination); err != nil {
		return fmt.Errorf("invalid JSON body: %w", err)
	}
	if err := decoder.Decode(&struct{}{}); !errors.Is(err, io.EOF) {
		return errors.New("body must contain one JSON object")
	}
	return nil
}

func method(writer http.ResponseWriter, request *http.Request, allowed string) bool {
	if request.Method == allowed {
		return true
	}
	writer.Header().Set("Allow", allowed)
	writeJSON(writer, http.StatusMethodNotAllowed, map[string]string{"error": "method not allowed"})
	return false
}

func writeJSON(writer http.ResponseWriter, status int, value any) {
	writer.Header().Set("Content-Type", "application/json; charset=utf-8")
	writer.Header().Set("Cache-Control", "no-store")
	writer.WriteHeader(status)
	_ = json.NewEncoder(writer).Encode(value)
}

func statusForError(err error) int {
	if errors.Is(err, context.DeadlineExceeded) || errors.Is(err, os.ErrDeadlineExceeded) || strings.Contains(strings.ToLower(err.Error()), "timeout") {
		return http.StatusGatewayTimeout
	}
	return http.StatusBadGateway
}

func sortedRankingServices(prediction map[string]any) []string {
	raw, _ := prediction["ranking"].([]any)
	services := make([]string, 0, len(raw))
	for _, value := range raw {
		entry, _ := value.(map[string]any)
		service, _ := entry["service"].(string)
		services = append(services, service)
	}
	sort.Strings(services)
	return services
}
