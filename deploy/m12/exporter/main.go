package main

import (
	"context"
	"encoding/json"
	"fmt"
	"log"
	"net"
	"net/http"
	"sort"
	"sync"
	"time"
)

const api = "http://docker/v1.44"

type container struct {
	ID     string            `json:"Id"`
	Labels map[string]string `json:"Labels"`
}

type stats struct {
	CPUStats struct {
		CPUUsage struct {
			Total uint64 `json:"total_usage"`
		} `json:"cpu_usage"`
		System uint64 `json:"system_cpu_usage"`
		Online uint64 `json:"online_cpus"`
	} `json:"cpu_stats"`
	PreCPUStats struct {
		CPUUsage struct {
			Total uint64 `json:"total_usage"`
		} `json:"cpu_usage"`
		System uint64 `json:"system_cpu_usage"`
	} `json:"precpu_stats"`
	Memory struct {
		Usage uint64            `json:"usage"`
		Stats map[string]uint64 `json:"stats"`
	} `json:"memory_stats"`
	Networks map[string]struct {
		Rx uint64 `json:"rx_bytes"`
		Tx uint64 `json:"tx_bytes"`
	} `json:"networks"`
}

type sample struct {
	service        string
	cpu            float64
	memory, rx, tx uint64
}

var state struct {
	sync.RWMutex
	samples []sample
}

func dockerClient() *http.Client {
	return &http.Client{Transport: &http.Transport{DialContext: func(ctx context.Context, _, _ string) (net.Conn, error) {
		return (&net.Dialer{}).DialContext(ctx, "unix", "/var/run/docker.sock")
	}}, Timeout: 5 * time.Second}
}

func readJSON(client *http.Client, path string, target any) error {
	response, err := client.Get(api + path)
	if err != nil {
		return err
	}
	defer response.Body.Close()
	if response.StatusCode != 200 {
		return fmt.Errorf("docker API %s: %s", path, response.Status)
	}
	return json.NewDecoder(response.Body).Decode(target)
}

func collect(client *http.Client) error {
	var containers []container
	if err := readJSON(client, "/containers/json", &containers); err != nil {
		return err
	}
	results := make(chan sample, len(containers))
	errors := make(chan error, len(containers))
	var group sync.WaitGroup
	for _, item := range containers {
		if item.Labels["io.vkr.m12.role"] != "application" {
			continue
		}
		group.Add(1)
		go func(item container) {
			defer group.Done()
			var value stats
			if err := readJSON(client, "/containers/"+item.ID+"/stats?stream=false", &value); err != nil {
				errors <- err
				return
			}
			cpuDelta := value.CPUStats.CPUUsage.Total - value.PreCPUStats.CPUUsage.Total
			systemDelta := value.CPUStats.System - value.PreCPUStats.System
			cores := float64(0)
			if systemDelta > 0 {
				cores = float64(cpuDelta) / float64(systemDelta) * float64(value.CPUStats.Online)
			}
			memory := value.Memory.Usage
			if cache := value.Memory.Stats["inactive_file"]; memory > cache {
				memory -= cache
			}
			var rx, tx uint64
			for _, network := range value.Networks {
				rx += network.Rx
				tx += network.Tx
			}
			results <- sample{item.Labels["com.docker.compose.service"], cores, memory, rx, tx}
		}(item)
	}
	group.Wait()
	close(results)
	close(errors)
	if err := <-errors; err != nil {
		return err
	}
	result := make([]sample, 0, len(containers))
	for item := range results {
		result = append(result, item)
	}
	sort.Slice(result, func(i, j int) bool { return result[i].service < result[j].service })
	state.Lock()
	state.samples = result
	state.Unlock()
	return nil
}

func metrics(w http.ResponseWriter, _ *http.Request) {
	w.Header().Set("Content-Type", "text/plain; version=0.0.4")
	state.RLock()
	defer state.RUnlock()
	for _, item := range state.samples {
		label := fmt.Sprintf("service=%q", item.service)
		fmt.Fprintf(w, "m12_container_cpu_cores{%s} %.9f\n", label, item.cpu)
		fmt.Fprintf(w, "m12_container_memory_working_set_bytes{%s} %d\n", label, item.memory)
		fmt.Fprintf(w, "m12_container_network_receive_bytes_total{%s} %d\n", label, item.rx)
		fmt.Fprintf(w, "m12_container_network_transmit_bytes_total{%s} %d\n", label, item.tx)
	}
}

func main() {
	client := dockerClient()
	go func() {
		for {
			started := time.Now()
			if err := collect(client); err != nil {
				log.Printf("collect: %v", err)
			}
			time.Sleep(max(0, time.Second-time.Since(started)))
		}
	}()
	http.HandleFunc("/metrics", metrics)
	log.Fatal(http.ListenAndServe(":9100", nil))
}
