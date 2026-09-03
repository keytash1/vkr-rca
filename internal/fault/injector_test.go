package fault

import (
	"context"
	"errors"
	"sync"
	"testing"
	"time"
)

func TestDefaultConfigIsHealthy(t *testing.T) {
	if got := New().GetConfig(); got != (Config{}) {
		t.Fatalf("default config = %+v, want healthy config", got)
	}
}

func TestSetGetAndReset(t *testing.T) {
	injector := New()
	want := Config{LatencyMS: 700, ErrorRate: 0.5}
	if err := injector.SetConfig(want); err != nil {
		t.Fatalf("set config: %v", err)
	}
	if got := injector.GetConfig(); got != want {
		t.Fatalf("config = %+v, want %+v", got, want)
	}
	if got := injector.Reset(); got != (Config{}) {
		t.Fatalf("reset result = %+v, want healthy config", got)
	}
	if got := injector.GetConfig(); got != (Config{}) {
		t.Fatalf("config after reset = %+v, want healthy config", got)
	}
}

func TestSetConfigRejectsInvalidValues(t *testing.T) {
	tests := []struct {
		name   string
		config Config
	}{
		{name: "negative latency", config: Config{LatencyMS: -1}},
		{name: "negative error rate", config: Config{ErrorRate: -0.01}},
		{name: "error rate greater than one", config: Config{ErrorRate: 1.01}},
	}

	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			injector := New()
			if err := injector.SetConfig(test.config); err == nil {
				t.Fatalf("SetConfig(%+v) returned no error", test.config)
			}
			if got := injector.GetConfig(); got != (Config{}) {
				t.Fatalf("invalid update changed config to %+v", got)
			}
		})
	}
}

func TestErrorRateBoundaries(t *testing.T) {
	for _, test := range []struct {
		name      string
		errorRate float64
		wantError bool
	}{
		{name: "zero never injects", errorRate: 0, wantError: false},
		{name: "one always injects", errorRate: 1, wantError: true},
	} {
		t.Run(test.name, func(t *testing.T) {
			injector := newWithRandom(func() float64 {
				t.Fatal("random source must not be called for boundary rates")
				return 0
			})
			if err := injector.SetConfig(Config{ErrorRate: test.errorRate}); err != nil {
				t.Fatalf("set config: %v", err)
			}
			outcome, err := injector.Apply(context.Background())
			if errors.Is(err, ErrInjected) != test.wantError {
				t.Fatalf("injected error = %v, want %v", err, test.wantError)
			}
			if outcome.ErrorInjected != test.wantError {
				t.Fatalf("outcome.ErrorInjected = %v, want %v", outcome.ErrorInjected, test.wantError)
			}
		})
	}
}

func TestIntermediateErrorRateUsesInjectedRandomSource(t *testing.T) {
	values := []float64{0.49, 0.50}
	injector := newWithRandom(func() float64 {
		value := values[0]
		values = values[1:]
		return value
	})
	if err := injector.SetConfig(Config{ErrorRate: 0.5}); err != nil {
		t.Fatalf("set config: %v", err)
	}

	if _, err := injector.Apply(context.Background()); !errors.Is(err, ErrInjected) {
		t.Fatalf("random value below rate returned %v, want injected error", err)
	}
	if _, err := injector.Apply(context.Background()); err != nil {
		t.Fatalf("random value equal to rate returned %v, want success", err)
	}
}

func TestLatencyRespectsContextCancellation(t *testing.T) {
	injector := New()
	if err := injector.SetConfig(Config{LatencyMS: 500}); err != nil {
		t.Fatalf("set config: %v", err)
	}
	ctx, cancel := context.WithCancel(context.Background())
	cancel()

	startedAt := time.Now()
	outcome, err := injector.Apply(ctx)
	if !errors.Is(err, context.Canceled) {
		t.Fatalf("Apply error = %v, want context.Canceled", err)
	}
	if outcome.LatencyMS != 500 {
		t.Fatalf("outcome latency = %d, want 500", outcome.LatencyMS)
	}
	if elapsed := time.Since(startedAt); elapsed > 100*time.Millisecond {
		t.Fatalf("cancelled Apply took %v, want less than 100ms", elapsed)
	}
}

func TestConcurrentSetGetApply(t *testing.T) {
	injector := New()
	const goroutines = 8
	const iterations = 100

	var waitGroup sync.WaitGroup
	for worker := 0; worker < goroutines; worker++ {
		waitGroup.Add(1)
		go func(worker int) {
			defer waitGroup.Done()
			for index := 0; index < iterations; index++ {
				config := Config{ErrorRate: float64((worker + index) % 2)}
				if err := injector.SetConfig(config); err != nil {
					t.Errorf("set config: %v", err)
					return
				}
				_ = injector.GetConfig()
				_, _ = injector.Apply(context.Background())
			}
		}(worker)
	}
	waitGroup.Wait()
}
