package demo

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"sort"
	"sync/atomic"
	"time"
)

type Scenario string

const (
	ScenarioHealthy        Scenario = "healthy"
	ScenarioGatewayLatency Scenario = "gateway_latency"
	ScenarioOrdersLatency  Scenario = "orders_latency"
	ScenarioPaymentLatency Scenario = "payment_latency"
	ScenarioGatewayError   Scenario = "gateway_error"
	ScenarioOrdersError    Scenario = "orders_error"
	ScenarioPaymentError   Scenario = "payment_error"
)

var ValidScenarios = []Scenario{
	ScenarioHealthy, ScenarioGatewayLatency, ScenarioOrdersLatency, ScenarioPaymentLatency,
	ScenarioGatewayError, ScenarioOrdersError, ScenarioPaymentError,
}

type LiveConfig struct {
	GatewayURL       string
	OrdersURL        string
	PaymentURL       string
	RCAURL           string
	RequestTimeout   time.Duration
	DrainDuration    time.Duration
	BaselineRequests int
}

type LiveClient struct {
	config  LiveConfig
	client  *http.Client
	counter atomic.Uint64
}

type TrafficResult struct {
	Requests int      `json:"requests"`
	TraceIDs []string `json:"trace_ids"`
	Statuses []int    `json:"http_statuses"`
}

type LiveResult struct {
	Scenario  Scenario       `json:"scenario"`
	TraceIDs  []string       `json:"trace_ids"`
	Graph     map[string]any `json:"graph"`
	Features  map[string]any `json:"features"`
	RCA       map[string]any `json:"rca"`
	Anomalies map[string]any `json:"anomalies"`
	Trace     map[string]any `json:"latest_trace,omitempty"`
	Label     string         `json:"label"`
}

func NewLiveClient(config LiveConfig) (*LiveClient, error) {
	if config.GatewayURL == "" || config.OrdersURL == "" || config.PaymentURL == "" || config.RCAURL == "" {
		return nil, errors.New("all live service URLs are required")
	}
	if config.RequestTimeout <= 0 || config.DrainDuration < 0 || config.BaselineRequests < 30 {
		return nil, errors.New("invalid live demo timeout, drain, or baseline configuration")
	}
	return &LiveClient{config: config, client: &http.Client{Timeout: config.RequestTimeout}}, nil
}

func ParseScenario(value string) (Scenario, error) {
	for _, scenario := range ValidScenarios {
		if string(scenario) == value {
			return scenario, nil
		}
	}
	return "", fmt.Errorf("unsupported live scenario %q", value)
}

func (live *LiveClient) Reset(ctx context.Context) error {
	if err := live.checkHealth(ctx); err != nil {
		return err
	}
	if err := live.resetFaults(ctx); err != nil {
		return err
	}
	if _, err := live.post(ctx, live.config.RCAURL+"/debug/baseline/start", nil); err != nil {
		return fmt.Errorf("start baseline: %w", err)
	}
	if _, err := live.sendTraffic(ctx, live.config.BaselineRequests); err != nil {
		return fmt.Errorf("generate baseline traffic: %w", err)
	}
	if err := waitContext(ctx, live.config.DrainDuration); err != nil {
		return err
	}
	if _, err := live.post(ctx, live.config.RCAURL+"/debug/baseline/freeze", nil); err != nil {
		return fmt.Errorf("freeze baseline: %w", err)
	}
	if err := live.clearIncident(ctx); err != nil {
		return err
	}
	if err := waitContext(ctx, live.config.DrainDuration); err != nil {
		return err
	}
	if err := live.clearIncident(ctx); err != nil {
		return err
	}
	return live.checkHealth(ctx)
}

func (live *LiveClient) ApplyScenario(ctx context.Context, scenario Scenario) error {
	if _, err := ParseScenario(string(scenario)); err != nil {
		return err
	}
	if err := live.resetFaults(ctx); err != nil {
		return err
	}
	if scenario == ScenarioHealthy {
		return nil
	}
	service, kind := scenarioTarget(scenario)
	service = live.serviceURL(service)
	config := map[string]any{"latency_ms": 0, "error_rate": 0.0}
	if kind == "latency" {
		config["latency_ms"] = 700
	} else {
		config["error_rate"] = 1.0
	}
	if _, err := live.post(ctx, service+"/debug/fault", config); err != nil {
		return fmt.Errorf("apply %s: %w", scenario, err)
	}
	return nil
}

func (live *LiveClient) GenerateTraffic(ctx context.Context, count int) (TrafficResult, error) {
	if count <= 0 || count > 50 {
		return TrafficResult{}, errors.New("traffic count must be between 1 and 50")
	}
	result, err := live.sendTraffic(ctx, count)
	if err != nil {
		return TrafficResult{}, err
	}
	if err := waitContext(ctx, live.config.DrainDuration); err != nil {
		return TrafficResult{}, err
	}
	return result, nil
}

func (live *LiveClient) Snapshot(ctx context.Context, scenario Scenario, traceIDs []string) (LiveResult, error) {
	result := LiveResult{Scenario: scenario, TraceIDs: append([]string(nil), traceIDs...), Label: "Controlled live trace/topology RCA demo"}
	requests := []struct {
		path        string
		destination *map[string]any
	}{
		{live.config.RCAURL + "/api/graph", &result.Graph},
		{live.config.RCAURL + "/api/features", &result.Features},
		{live.config.RCAURL + "/api/rca", &result.RCA},
		{live.config.RCAURL + "/api/anomalies", &result.Anomalies},
	}
	for _, request := range requests {
		value, err := live.get(ctx, request.path)
		if err != nil {
			return LiveResult{}, err
		}
		*request.destination = value
	}
	if len(traceIDs) > 0 {
		trace, err := live.get(ctx, live.config.RCAURL+"/api/traces/"+traceIDs[len(traceIDs)-1])
		if err == nil {
			result.Trace = trace
		}
	}
	return result, nil
}

func (live *LiveClient) checkHealth(ctx context.Context) error {
	for name, endpoint := range map[string]string{
		"gateway": live.config.GatewayURL + "/health", "orders": live.config.OrdersURL + "/health",
		"payment": live.config.PaymentURL + "/health", "rca": live.config.RCAURL + "/health",
	} {
		if _, err := live.get(ctx, endpoint); err != nil {
			return fmt.Errorf("%s unavailable: %w", name, err)
		}
	}
	return nil
}

func (live *LiveClient) clearIncident(ctx context.Context) error {
	for _, endpoint := range []string{live.config.RCAURL + "/debug/reset", live.config.RCAURL + "/debug/anomaly/reset"} {
		if _, err := live.post(ctx, endpoint, nil); err != nil {
			return fmt.Errorf("clear live incident: %w", err)
		}
	}
	return nil
}

func (live *LiveClient) resetFaults(ctx context.Context) error {
	for _, endpoint := range []string{live.config.GatewayURL, live.config.OrdersURL, live.config.PaymentURL} {
		if _, err := live.post(ctx, endpoint+"/debug/reset", nil); err != nil {
			return fmt.Errorf("reset fault at %s: %w", endpoint, err)
		}
	}
	return nil
}

func (live *LiveClient) sendTraffic(ctx context.Context, count int) (TrafficResult, error) {
	result := TrafficResult{Requests: count}
	for range count {
		sequence, traceID, traceparent := live.nextTraceparent()
		request, err := http.NewRequestWithContext(ctx, http.MethodGet, live.config.GatewayURL+"/api/order", nil)
		if err != nil {
			return TrafficResult{}, err
		}
		request.Header.Set("traceparent", traceparent)
		request.Header.Set("X-Request-ID", fmt.Sprintf("m10b-demo-%06d", sequence))
		responseValue, err := live.client.Do(request)
		if err != nil {
			return TrafficResult{}, fmt.Errorf("live request failed: %w", err)
		}
		_, _ = io.Copy(io.Discard, responseValue.Body)
		_ = responseValue.Body.Close()
		result.TraceIDs = append(result.TraceIDs, traceID)
		result.Statuses = append(result.Statuses, responseValue.StatusCode)
	}
	return result, nil
}

func (live *LiveClient) nextTraceparent() (uint64, string, string) {
	sequence := live.counter.Add(1)
	digest := sha256.Sum256([]byte(fmt.Sprintf("vkr-rca-m10b-live-%d", sequence)))
	traceID := hex.EncodeToString(digest[:16])
	spanID := hex.EncodeToString(digest[16:24])
	return sequence, traceID, "00-" + traceID + "-" + spanID + "-01"
}

func scenarioTarget(scenario Scenario) (string, string) {
	var service, kind string
	switch scenario {
	case ScenarioGatewayLatency:
		service, kind = "gateway", "latency"
	case ScenarioOrdersLatency:
		service, kind = "orders", "latency"
	case ScenarioPaymentLatency:
		service, kind = "payment", "latency"
	case ScenarioGatewayError:
		service, kind = "gateway", "error"
	case ScenarioOrdersError:
		service, kind = "orders", "error"
	case ScenarioPaymentError:
		service, kind = "payment", "error"
	}
	return service, kind
}

func (live *LiveClient) serviceURL(name string) string {
	switch name {
	case "gateway":
		return live.config.GatewayURL
	case "orders":
		return live.config.OrdersURL
	case "payment":
		return live.config.PaymentURL
	default:
		return ""
	}
}

func (live *LiveClient) get(ctx context.Context, endpoint string) (map[string]any, error) {
	request, err := http.NewRequestWithContext(ctx, http.MethodGet, endpoint, nil)
	if err != nil {
		return nil, err
	}
	return live.do(request)
}

func (live *LiveClient) post(ctx context.Context, endpoint string, body any) (map[string]any, error) {
	var encoded io.Reader
	if body != nil {
		data, err := json.Marshal(body)
		if err != nil {
			return nil, err
		}
		encoded = bytes.NewReader(data)
	}
	request, err := http.NewRequestWithContext(ctx, http.MethodPost, endpoint, encoded)
	if err != nil {
		return nil, err
	}
	if body != nil {
		request.Header.Set("Content-Type", "application/json")
	}
	return live.do(request)
}

func (live *LiveClient) do(request *http.Request) (map[string]any, error) {
	response, err := live.client.Do(request)
	if err != nil {
		return nil, err
	}
	defer response.Body.Close()
	data, err := io.ReadAll(io.LimitReader(response.Body, 8<<20))
	if err != nil {
		return nil, err
	}
	if response.StatusCode < 200 || response.StatusCode >= 300 {
		return nil, fmt.Errorf("%s returned %d: %s", request.URL, response.StatusCode, string(data))
	}
	if len(data) == 0 {
		return map[string]any{}, nil
	}
	var result map[string]any
	if err := json.Unmarshal(data, &result); err != nil {
		return nil, fmt.Errorf("decode %s: %w", request.URL, err)
	}
	return result, nil
}

func waitContext(ctx context.Context, duration time.Duration) error {
	timer := time.NewTimer(duration)
	defer timer.Stop()
	select {
	case <-ctx.Done():
		return ctx.Err()
	case <-timer.C:
		return nil
	}
}

func SortedScenarios() []string {
	result := make([]string, len(ValidScenarios))
	for index, scenario := range ValidScenarios {
		result[index] = string(scenario)
	}
	sort.Strings(result)
	return result
}
