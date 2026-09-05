package demo

import (
	"context"
	"encoding/json"
	"errors"
	"io/fs"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"runtime"
	"slices"
	"strings"
	"testing"
	"time"
)

func TestFrozenResearchAndModelRegistry(t *testing.T) {
	root := testRoot(t)
	freeze, err := VerifyFrozen(root)
	if err != nil {
		t.Fatal(err)
	}
	if freeze.Status != "identical" || len(freeze.Files) < 10 {
		t.Fatalf("unexpected freeze status: %+v", freeze)
	}
	registry, err := LoadModelRegistry(root)
	if err != nil {
		t.Fatal(err)
	}
	if len(registry.Models) != 4 || registry.Models[0].Status != "final" {
		t.Fatalf("unexpected model registry: %+v", registry)
	}
	results, err := LoadResearch(root, freeze, registry)
	if err != nil {
		t.Fatal(err)
	}
	claims, ok := results["claims"].([]Claim)
	if !ok || len(claims) != 7 || claims[6].Status != "REJECTED" {
		t.Fatalf("frozen claims not loaded: %#v", results["claims"])
	}
}

func TestScenarioValidationAndSorting(t *testing.T) {
	for _, value := range ValidScenarios {
		if parsed, err := ParseScenario(string(value)); err != nil || parsed != value {
			t.Fatalf("scenario %s rejected: %v", value, err)
		}
	}
	if _, err := ParseScenario("invented_fault"); err == nil {
		t.Fatal("unknown fault family accepted")
	}
	values := SortedScenarios()
	if !slices.IsSorted(values) || len(values) != 7 {
		t.Fatalf("scenarios are not deterministically sorted: %v", values)
	}
}

func TestPredictionJSONValidation(t *testing.T) {
	valid := map[string]any{"ranking": []any{
		map[string]any{"rank": float64(1), "service": "orders", "score": 2.0},
		map[string]any{"rank": float64(2), "service": "payment", "score": 1.0},
	}}
	if err := validatePredictionJSON(valid); err != nil {
		t.Fatal(err)
	}
	leaked := map[string]any{"ranking": valid["ranking"], "root_service": "orders"}
	if err := validatePredictionJSON(leaked); err == nil {
		t.Fatal("ground truth leaked into prediction")
	}
	unsorted := map[string]any{"ranking": []any{
		map[string]any{"rank": float64(1), "service": "payment", "score": 1.0},
		map[string]any{"rank": float64(2), "service": "orders", "score": 2.0},
	}}
	if err := validatePredictionJSON(unsorted); err == nil {
		t.Fatal("nondeterministic ranking order accepted")
	}
}

func TestStaticFrontendContractHasTabsAndNoExternalAssets(t *testing.T) {
	root := testRoot(t)
	staticRoot := filepath.Join(root, "cmd/demo/static")
	wanted := []string{"Живая демонстрация", "Внешний набор данных", "Результаты исследования", "Архитектура", "Как пользоваться"}
	index, err := os.ReadFile(filepath.Join(staticRoot, "index.html"))
	if err != nil {
		t.Fatal(err)
	}
	for _, label := range wanted {
		if !strings.Contains(string(index), label) {
			t.Fatalf("frontend missing tab %q", label)
		}
	}
	err = filepath.WalkDir(staticRoot, func(path string, entry fs.DirEntry, err error) error {
		if err != nil || entry.IsDir() {
			return err
		}
		data, readErr := os.ReadFile(path)
		if readErr != nil {
			return readErr
		}
		content := strings.ToLower(string(data))
		if strings.Contains(content, "https://") || strings.Contains(content, "cdn.") {
			t.Fatalf("external frontend dependency in %s", path)
		}
		return nil
	})
	if err != nil {
		t.Fatal(err)
	}
}

func TestRussianGuidanceWelcomeAndTooltips(t *testing.T) {
	root := testRoot(t)
	index, err := os.ReadFile(filepath.Join(root, "cmd/demo/static/index.html"))
	if err != nil {
		t.Fatal(err)
	}
	app, err := os.ReadFile(filepath.Join(root, "cmd/demo/static/app.js"))
	if err != nil {
		t.Fatal(err)
	}
	markup, script := string(index), string(app)
	for _, text := range []string{
		"Быстрый старт", "Почему недостаточно найти самый медленный сервис", "Локальное время сервиса",
		"Где здесь машинное обучение", "Почему показан неудачный эксперимент", "Ограничения системы",
		"welcome-guide", "welcome-demo",
	} {
		if !strings.Contains(markup, text) {
			t.Fatalf("guidance missing %q", text)
		}
	}
	for _, term := range []string{
		"RCA", "Latency", "Error rate", "Trace", "Span", "Topology", "Exclusive duration",
		"Ranking score", "LambdaMART", "AC@1", "AC@3", "MRR", "SHAP", "Ground truth",
	} {
		if !strings.Contains(script, `"`+term+`":`) {
			t.Fatalf("tooltip dictionary missing %q", term)
		}
	}
	if !strings.Contains(script, "sessionStorage") || !strings.Contains(script, "m10b-welcome-seen") {
		t.Fatal("first-session welcome behavior is missing")
	}
	for _, frozenDisplay := range []string{"76.4%", "32.2%", "70.4%", "64.4%", "+0.038"} {
		if strings.Contains(markup, frozenDisplay) || strings.Contains(script, frozenDisplay) {
			t.Fatalf("frozen research result %q was hard-coded into frontend", frozenDisplay)
		}
	}
}

func TestTimeoutMapsToGatewayTimeout(t *testing.T) {
	if statusForError(context.DeadlineExceeded) != http.StatusGatewayTimeout {
		t.Fatal("deadline was not mapped to gateway timeout")
	}
	if statusForError(errors.New("upstream unavailable")) != http.StatusBadGateway {
		t.Fatal("upstream error was not mapped to bad gateway")
	}
}

func TestResearchEndpointUsesFrozenArtifactsAndBusyStateRejectsMutation(t *testing.T) {
	server := newTestServer(t)
	request := httptest.NewRequest(http.MethodGet, "/api/demo/research", nil)
	response := httptest.NewRecorder()
	server.Handler(os.DirFS(filepath.Join(testRoot(t), "cmd/demo/static"))).ServeHTTP(response, request)
	if response.Code != http.StatusOK {
		t.Fatalf("research endpoint returned %d: %s", response.Code, response.Body.String())
	}
	var body map[string]any
	if err := json.Unmarshal(response.Body.Bytes(), &body); err != nil {
		t.Fatal(err)
	}
	if body["status"] != "FROZEN_AT_M10A" {
		t.Fatalf("unexpected research status: %#v", body)
	}

	server.mutation.Lock()
	defer server.mutation.Unlock()
	request = httptest.NewRequest(http.MethodPost, "/api/demo/live/scenario", strings.NewReader(`{"scenario":"healthy"}`))
	request.Header.Set("Content-Type", "application/json")
	response = httptest.NewRecorder()
	server.Handler(os.DirFS(filepath.Join(testRoot(t), "cmd/demo/static"))).ServeHTTP(response, request)
	if response.Code != http.StatusConflict {
		t.Fatalf("concurrent mutation returned %d", response.Code)
	}
}

func newTestServer(t *testing.T) *Server {
	t.Helper()
	server, err := NewServer(Config{
		Root: testRoot(t), OperationTimeout: time.Second,
		Live: LiveConfig{
			GatewayURL: "http://127.0.0.1:1", OrdersURL: "http://127.0.0.1:1",
			PaymentURL: "http://127.0.0.1:1", RCAURL: "http://127.0.0.1:1",
			RequestTimeout: 10 * time.Millisecond, DrainDuration: time.Millisecond, BaselineRequests: 30,
		},
	})
	if err != nil {
		t.Fatal(err)
	}
	return server
}

func testRoot(t *testing.T) string {
	t.Helper()
	_, file, _, ok := runtime.Caller(0)
	if !ok {
		t.Fatal("resolve test path")
	}
	return filepath.Clean(filepath.Join(filepath.Dir(file), "../.."))
}
