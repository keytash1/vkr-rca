package demo

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"sort"
)

type FrozenManifest struct {
	FreezeCommit string            `json:"freeze_commit"`
	Files        map[string]string `json:"files"`
	Status       string            `json:"status"`
}

type FreezeFile struct {
	Path      string `json:"path"`
	Expected  string `json:"expected_sha256"`
	Actual    string `json:"actual_sha256"`
	Identical bool   `json:"identical"`
}

type FreezeStatus struct {
	Status       string       `json:"status"`
	FreezeCommit string       `json:"freeze_commit"`
	Files        []FreezeFile `json:"files"`
}

func VerifyFrozen(root string) (FreezeStatus, error) {
	var manifest FrozenManifest
	if err := readJSON(filepath.Join(root, "demo/frozen-research.json"), &manifest); err != nil {
		return FreezeStatus{}, fmt.Errorf("load research freeze manifest: %w", err)
	}
	paths := make([]string, 0, len(manifest.Files))
	for path := range manifest.Files {
		paths = append(paths, path)
	}
	sort.Strings(paths)
	status := FreezeStatus{Status: "identical", FreezeCommit: manifest.FreezeCommit}
	for _, path := range paths {
		actual, err := fileSHA256(filepath.Join(root, filepath.FromSlash(path)))
		if err != nil {
			return FreezeStatus{}, fmt.Errorf("hash frozen artifact %s: %w", path, err)
		}
		expected := manifest.Files[path]
		file := FreezeFile{Path: path, Expected: expected, Actual: actual, Identical: actual == expected}
		status.Files = append(status.Files, file)
		if !file.Identical {
			status.Status = "mismatch"
		}
	}
	if status.Status != "identical" {
		return status, fmt.Errorf("frozen research artifacts changed")
	}
	return status, nil
}

func fileSHA256(path string) (string, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return "", err
	}
	digest := sha256.Sum256(data)
	return hex.EncodeToString(digest[:]), nil
}

func readJSON(path string, destination any) error {
	data, err := os.ReadFile(path)
	if err != nil {
		return err
	}
	if err := json.Unmarshal(data, destination); err != nil {
		return err
	}
	return nil
}
