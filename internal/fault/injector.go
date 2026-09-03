package fault

import (
	"context"
	"errors"
	"math"
	"math/rand/v2"
	"sync"
	"sync/atomic"
	"time"
)

var ErrInjected = errors.New("fault injected")

type Config struct {
	LatencyMS int     `json:"latency_ms"`
	ErrorRate float64 `json:"error_rate"`
}

type Outcome struct {
	LatencyMS     int
	ErrorRate     float64
	ErrorInjected bool
}

type Injector struct {
	config atomic.Value

	randomMu sync.Mutex
	random   func() float64
}

func New() *Injector {
	return newWithRandom(rand.Float64)
}

func newWithRandom(random func() float64) *Injector {
	injector := &Injector{random: random}
	injector.config.Store(Config{})
	return injector
}

func (injector *Injector) GetConfig() Config {
	return injector.config.Load().(Config)
}

func (injector *Injector) SetConfig(config Config) error {
	if err := config.Validate(); err != nil {
		return err
	}

	injector.config.Store(config)
	return nil
}

func (injector *Injector) Reset() Config {
	config := Config{}
	injector.config.Store(config)
	return config
}

func (injector *Injector) Apply(ctx context.Context) (Outcome, error) {
	config := injector.GetConfig()
	outcome := Outcome{LatencyMS: config.LatencyMS, ErrorRate: config.ErrorRate}

	if config.LatencyMS > 0 {
		timer := time.NewTimer(time.Duration(config.LatencyMS) * time.Millisecond)
		defer timer.Stop()

		select {
		case <-ctx.Done():
			return outcome, ctx.Err()
		case <-timer.C:
		}
	}

	if injector.shouldInjectError(config.ErrorRate) {
		outcome.ErrorInjected = true
		return outcome, ErrInjected
	}

	return outcome, nil
}

func (config Config) Validate() error {
	if config.LatencyMS < 0 {
		return errors.New("latency_ms must be greater than or equal to 0")
	}
	if math.IsNaN(config.ErrorRate) || math.IsInf(config.ErrorRate, 0) || config.ErrorRate < 0 || config.ErrorRate > 1 {
		return errors.New("error_rate must be between 0 and 1")
	}
	return nil
}

func (injector *Injector) shouldInjectError(errorRate float64) bool {
	if errorRate <= 0 {
		return false
	}
	if errorRate >= 1 {
		return true
	}

	injector.randomMu.Lock()
	value := injector.random()
	injector.randomMu.Unlock()
	return value < errorRate
}
