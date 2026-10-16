// The acceptance exporter observes Docker resource counters for one Compose project.
package main

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"log"
	"net"
	"net/http"
	"net/url"
	"os"
	"sort"
	"sync"
	"time"
)

type container struct {
	ID     string            `json:"Id"`
	Labels map[string]string `json:"Labels"`
}

type stats struct {
	Read     time.Time `json:"read"`
	CPUStats struct {
		CPUUsage struct {
			Total uint64 `json:"total_usage"`
		} `json:"cpu_usage"`
		System uint64 `json:"system_cpu_usage"`
		Online uint64 `json:"online_cpus"`
	} `json:"cpu_stats"`
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
	service, instance string
	cpu               float64
	cpuReady          bool
	memoryReady       bool
	networkReady      bool
	memory, rx, tx    uint64
}

// one-shot does not populate precpu_stats. Keep two readings of the same
// container and divide consumed CPU nanoseconds by elapsed wall nanoseconds.
// A first reading or counter reset is unavailable, not an observed idle CPU.
func cpuCores(previous, current stats) (float64, bool) {
	elapsed := current.Read.Sub(previous.Read)
	if previous.Read.IsZero() || current.Read.IsZero() || elapsed <= 0 || current.CPUStats.CPUUsage.Total < previous.CPUStats.CPUUsage.Total {
		return 0, false
	}
	return float64(current.CPUStats.CPUUsage.Total-previous.CPUStats.CPUUsage.Total) / float64(elapsed.Nanoseconds()), true
}

func workingSet(value stats) uint64 {
	cache, ok := value.Memory.Stats["inactive_file"]
	if !ok {
		cache = value.Memory.Stats["total_inactive_file"]
	}
	if value.Memory.Usage < cache {
		return 0
	}
	return value.Memory.Usage - cache
}

var state struct {
	sync.RWMutex
	samples []sample
	updated time.Time
}

func readJSON(client *http.Client, path string, value any) error {
	response, err := client.Get("http://docker/v1.44" + path)
	if err != nil {
		return err
	}
	defer response.Body.Close()
	if response.StatusCode != http.StatusOK {
		return fmt.Errorf("docker: %s", response.Status)
	}
	return json.NewDecoder(io.LimitReader(response.Body, 16<<20)).Decode(value)
}

func collect(client *http.Client, project string, previous map[string]stats) error {
	filters, _ := json.Marshal(map[string][]string{"label": {
		"com.docker.compose.project=" + project, "io.vkr.telemetry=enabled",
	}})
	var containers []container
	if err := readJSON(client, "/containers/json?filters="+url.QueryEscape(string(filters)), &containers); err != nil {
		return err
	}
	var samples []sample
	next := make(map[string]stats)
	for _, item := range containers {
		var value stats
		if err := readJSON(client, "/containers/"+item.ID+"/stats?stream=false&one-shot=true", &value); err != nil {
			return err
		}
		if value.Read.IsZero() || time.Since(value.Read) > 10*time.Second {
			return fmt.Errorf("no fresh stats for %s", item.ID)
		}
		cpu, ready := cpuCores(previous[item.ID], value)
		next[item.ID] = value
		var rx, tx uint64
		for _, network := range value.Networks {
			rx += network.Rx
			tx += network.Tx
		}
		samples = append(samples, sample{
			service: item.Labels["com.docker.compose.service"], instance: item.ID[:12],
			cpu: cpu, cpuReady: ready, memory: workingSet(value), memoryReady: value.Memory.Stats != nil,
			rx: rx, tx: tx, networkReady: len(value.Networks) > 0,
		})
	}
	if len(samples) == 0 {
		return fmt.Errorf("no instrumented application containers for %s", project)
	}
	clear(previous)
	for id, value := range next {
		previous[id] = value
	}
	sort.Slice(samples, func(i, j int) bool { return samples[i].instance < samples[j].instance })
	state.Lock()
	state.samples = samples
	state.updated = time.Now()
	state.Unlock()
	return nil
}

func main() {
	project := os.Getenv("COMPOSE_PROJECT")
	if project == "" {
		log.Fatal("COMPOSE_PROJECT is required")
	}
	client := &http.Client{Timeout: 5 * time.Second, Transport: &http.Transport{
		DialContext: func(ctx context.Context, _, _ string) (net.Conn, error) {
			return (&net.Dialer{}).DialContext(ctx, "unix", "/var/run/docker.sock")
		},
	}}
	go func() {
		previous := make(map[string]stats)
		for {
			if err := collect(client, project, previous); err != nil {
				log.Print(err)
			}
			time.Sleep(time.Second)
		}
	}()
	http.HandleFunc("/metrics", func(w http.ResponseWriter, _ *http.Request) {
		state.RLock()
		defer state.RUnlock()
		if state.updated.IsZero() || time.Since(state.updated) > 10*time.Second {
			http.Error(w, "no fresh Docker samples", 503)
			return
		}
		w.Header().Set("Content-Type", "text/plain; version=0.0.4")
		fmt.Fprintf(w, "rca_resource_snapshot_timestamp_seconds %.3f\n", float64(state.updated.UnixMilli())/1000)
		for _, x := range state.samples {
			labels := fmt.Sprintf("service=%q,instance=%q", x.service, x.instance)
			if x.cpuReady {
				fmt.Fprintf(w, "rca_container_cpu_cores{%s} %.9f\n", labels, x.cpu)
			}
			if x.memoryReady {
				fmt.Fprintf(w, "rca_container_memory_working_set_bytes{%s} %d\n", labels, x.memory)
			}
			if x.networkReady {
				fmt.Fprintf(w, "rca_container_network_receive_bytes_total{%s} %d\n", labels, x.rx)
				fmt.Fprintf(w, "rca_container_network_transmit_bytes_total{%s} %d\n", labels, x.tx)
			}
		}
	})
	log.Fatal(http.ListenAndServe(":9100", nil))
}
