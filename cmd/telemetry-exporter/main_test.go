package main

import (
	"testing"
	"time"
)

func TestCPUUsesSuccessiveReadingsNotLifetimeAverage(t *testing.T) {
	previous, current := stats{}, stats{}
	previous.Read = time.Unix(1000, 0)
	current.Read = previous.Read.Add(2 * time.Second)
	previous.CPUStats.CPUUsage.Total = 90_000_000_000
	current.CPUStats.CPUUsage.Total = 91_000_000_000
	got, ready := cpuCores(previous, current)
	if !ready || got != 0.5 {
		t.Fatalf("got %v, ready %v; expected half a CPU core", got, ready)
	}
	if _, ready := cpuCores(stats{}, current); ready {
		t.Fatal("first snapshot must not be exported as zero CPU")
	}
	current.CPUStats.CPUUsage.Total = 1
	if _, ready := cpuCores(previous, current); ready {
		t.Fatal("reset must not underflow the counter")
	}
	current.Read = previous.Read
	if _, ready := cpuCores(previous, current); ready {
		t.Fatal("duplicate snapshot must not create a CPU observation")
	}
}

func TestMemoryWorkingSetBothCgroupVersions(t *testing.T) {
	for _, key := range []string{"inactive_file", "total_inactive_file"} {
		value := stats{}
		value.Memory.Usage = 1000
		value.Memory.Stats = map[string]uint64{key: 200}
		if got := workingSet(value); got != 800 {
			t.Fatalf("%s: got %d", key, got)
		}
		value.Memory.Usage = 100
		if got := workingSet(value); got != 0 {
			t.Fatalf("cache underflow: %d", got)
		}
	}
}
