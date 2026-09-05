package demo

import (
	"bufio"
	"fmt"
	"os"
	"path/filepath"
	"strings"
)

type ModelRegistry struct {
	Models []ModelEntry `json:"models"`
}

type ModelEntry struct {
	Version           string   `json:"version"`
	Fold              string   `json:"fold,omitempty"`
	Artifact          string   `json:"artifact"`
	Schema            string   `json:"schema"`
	TrainingSystems   []string `json:"training_systems"`
	EvaluationSystems []string `json:"evaluation_systems,omitempty"`
	FeatureCount      int      `json:"feature_count"`
	SHA256            string   `json:"sha256"`
	Status            string   `json:"status"`
}

type Claim struct {
	Number      int    `json:"number"`
	Claim       string `json:"claim"`
	Hypothesis  string `json:"hypothesis"`
	Status      string `json:"status"`
	Denominator string `json:"denominator"`
	Result      string `json:"result"`
	CI          string `json:"ci"`
	Limitation  string `json:"limitation"`
}

func LoadModelRegistry(root string) (ModelRegistry, error) {
	var registry ModelRegistry
	if err := readJSON(filepath.Join(root, "demo/model-registry.json"), &registry); err != nil {
		return ModelRegistry{}, err
	}
	if len(registry.Models) < 4 {
		return ModelRegistry{}, fmt.Errorf("model registry is incomplete")
	}
	for _, model := range registry.Models {
		actual, err := fileSHA256(filepath.Join(root, filepath.FromSlash(model.Artifact)))
		if err != nil {
			return ModelRegistry{}, err
		}
		if actual != model.SHA256 {
			return ModelRegistry{}, fmt.Errorf("model registry hash mismatch for %s", model.Artifact)
		}
	}
	return registry, nil
}

func LoadResearch(root string, freeze FreezeStatus, registry ModelRegistry) (map[string]any, error) {
	m10a, err := loadMap(filepath.Join(root, "ml/models/m10a-freeze/evaluation.json"))
	if err != nil {
		return nil, err
	}
	m9b, err := loadMap(filepath.Join(root, "ml/models/m9b-v1/evaluation.json"))
	if err != nil {
		return nil, err
	}
	m9a, err := loadMap(filepath.Join(root, "ml/models/m9a-detector-v2/evaluation.json"))
	if err != nil {
		return nil, err
	}
	claims, err := parseClaims(filepath.Join(root, "docs/thesis-claims.md"))
	if err != nil {
		return nil, err
	}
	return map[string]any{
		"status": "FROZEN_AT_M10A",
		"freeze": freeze,
		"models": registry.Models,
		"metrics": map[string]any{
			"metric_conditional":    nested(m10a, "metric_denominators", "conditional_root_observable", "overall"),
			"metric_full_360":       nested(m10a, "metric_denominators", "full_360", "overall"),
			"fusion_all_modalities": nested(m10a, "fusion", "all_modalities"),
			"fusion_metrics_only":   nested(m10a, "fusion", "metrics_only"),
			"fusion_paired":         nested(m10a, "fusion", "paired_all_minus_metrics"),
			"baro":                  nested(m10a, "baro_comparison", "comparison", "baro"),
			"baro_paired":           nested(m10a, "baro_comparison", "comparison", "paired_m9b_minus_baro"),
			"autonomous_m5":         nested(m9b, "multisource_study", "autonomous_m5_trigger"),
			"m9a_synthetic":         nested(m9a, "synthetic", "validation", "v2"),
			"m9a_external":          nested(m9a, "external", "by_dataset", "overall"),
			"m9a_verdict":           nested(m9a, "verdict"),
		},
		"claims": claims,
		"sources": map[string]string{
			"results": "ml/models/m10a-freeze/evaluation.json",
			"claims":  "docs/thesis-claims.md",
			"models":  "demo/model-registry.json (verified against frozen artifacts)",
		},
	}, nil
}

func LoadArchitecture(root string) (map[string]any, error) {
	path := filepath.Join(root, "docs/final-research-summary.md")
	data, err := os.ReadFile(path)
	if err != nil {
		return nil, err
	}
	return map[string]any{
		"research":       extractFirstCodeBlock(string(data)),
		"live":           []string{"Go microservices", "OpenTelemetry", "RCA graph + anomaly evidence", "M6 explainable online ranking"},
		"benchmark":      []string{"Pinned RCAEval case", "M9B truth-free features", "Frozen cross-system LambdaMART fold", "Top-K + predictive contribution evidence"},
		"primary_mode":   "externally triggered root-cause localization",
		"secondary_mode": "frozen M5/v1 detector followed by RCA",
		"rejected":       "M9A detector-v2",
		"source":         "docs/final-research-summary.md",
	}, nil
}

func loadMap(path string) (map[string]any, error) {
	var value map[string]any
	if err := readJSON(path, &value); err != nil {
		return nil, err
	}
	return value, nil
}

func nested(value any, path ...string) any {
	current := value
	for _, key := range path {
		mapping, ok := current.(map[string]any)
		if !ok {
			return nil
		}
		current = mapping[key]
	}
	return current
}

func parseClaims(path string) ([]Claim, error) {
	file, err := os.Open(path)
	if err != nil {
		return nil, err
	}
	defer file.Close()
	claims := []Claim{}
	current := Claim{}
	flush := func() {
		if current.Number > 0 {
			claims = append(claims, current)
			current = Claim{}
		}
	}
	scanner := bufio.NewScanner(file)
	for scanner.Scan() {
		line := scanner.Text()
		if strings.HasPrefix(line, "## Claim ") {
			flush()
			_, _ = fmt.Sscanf(line, "## Claim %d", &current.Number)
			continue
		}
		fields := []struct {
			prefix string
			target *string
		}{
			{"- **CLAIM:** ", &current.Claim}, {"- **HYPOTHESIS:** ", &current.Hypothesis},
			{"- **STATUS:** ", &current.Status}, {"- **DENOMINATOR:** ", &current.Denominator},
			{"- **RESULT:** ", &current.Result}, {"- **95% CI:** ", &current.CI},
			{"- **LIMITATION:** ", &current.Limitation},
		}
		for _, field := range fields {
			if strings.HasPrefix(line, field.prefix) {
				*field.target = strings.TrimSpace(strings.TrimPrefix(line, field.prefix))
				if field.target == &current.Status {
					*field.target = strings.TrimSuffix(*field.target, ".")
				}
			}
		}
	}
	flush()
	if err := scanner.Err(); err != nil {
		return nil, err
	}
	if len(claims) != 7 {
		return nil, fmt.Errorf("expected 7 frozen claims, got %d", len(claims))
	}
	return claims, nil
}

func extractFirstCodeBlock(markdown string) []string {
	lines := strings.Split(markdown, "\n")
	inside := false
	result := []string{}
	for _, line := range lines {
		if strings.HasPrefix(line, "```") {
			if inside {
				break
			}
			inside = true
			continue
		}
		if inside && strings.TrimSpace(line) != "" {
			result = append(result, strings.TrimSpace(line))
		}
	}
	return result
}
