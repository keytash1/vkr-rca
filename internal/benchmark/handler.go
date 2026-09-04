// Package benchmark provides a reusable, environment-configured service for
// controlled cross-topology RCA experiments.
package benchmark

import (
	"errors"
	"fmt"
	"io"
	"log/slog"
	"net/http"
	"net/url"
	"strings"
	"sync"

	"vkr-rca/internal/fault"
	"vkr-rca/internal/platform"
)

type CallMode string

const (
	CallSequential CallMode = "sequential"
	CallParallel   CallMode = "parallel"
)

type ResponsePolicy string

const (
	ResponsePropagate ResponsePolicy = "propagate"
	ResponseAlwaysOK  ResponsePolicy = "always_ok"
)

type Config struct {
	ServiceName    string
	DownstreamURLs []string
	CallMode       CallMode
	ResponsePolicy ResponsePolicy
	Client         *http.Client
	Logger         *slog.Logger
	Fault          *fault.Injector
}

type handler struct {
	serviceName    string
	downstreamURLs []string
	callMode       CallMode
	responsePolicy ResponsePolicy
	client         *http.Client
	logger         *slog.Logger
	fault          *fault.Injector
}

type downstreamResult struct {
	URL    string `json:"url"`
	Status int    `json:"status"`
	Error  string `json:"error,omitempty"`
}

func NewHandler(config Config) (http.Handler, error) {
	config.ServiceName = strings.TrimSpace(config.ServiceName)
	if config.ServiceName == "" {
		return nil, errors.New("service name is required")
	}
	if config.Client == nil || config.Logger == nil || config.Fault == nil {
		return nil, errors.New("client, logger and fault injector are required")
	}
	if config.CallMode == "" {
		config.CallMode = CallSequential
	}
	if config.CallMode != CallSequential && config.CallMode != CallParallel {
		return nil, fmt.Errorf("unsupported call mode %q", config.CallMode)
	}
	if config.ResponsePolicy == "" {
		config.ResponsePolicy = ResponsePropagate
	}
	if config.ResponsePolicy != ResponsePropagate && config.ResponsePolicy != ResponseAlwaysOK {
		return nil, fmt.Errorf("unsupported response policy %q", config.ResponsePolicy)
	}
	downstreams := make([]string, 0, len(config.DownstreamURLs))
	for _, raw := range config.DownstreamURLs {
		value := strings.TrimRight(strings.TrimSpace(raw), "/")
		if value == "" {
			continue
		}
		parsed, err := url.ParseRequestURI(value)
		if err != nil || (parsed.Scheme != "http" && parsed.Scheme != "https") || parsed.Host == "" {
			return nil, fmt.Errorf("invalid downstream URL %q", raw)
		}
		downstreams = append(downstreams, value)
	}

	application := &handler{
		serviceName:    config.ServiceName,
		downstreamURLs: downstreams,
		callMode:       config.CallMode,
		responsePolicy: config.ResponsePolicy,
		client:         config.Client,
		logger:         config.Logger,
		fault:          config.Fault,
	}
	mux := http.NewServeMux()
	mux.HandleFunc("/health", platform.HealthHandler(config.ServiceName))
	mux.HandleFunc("/work", application.work)
	mux.Handle("/debug/", fault.NewHandler(config.Fault))
	return platform.Middleware(config.Logger, mux), nil
}

func ParseDownstreamURLs(value string) []string {
	if strings.TrimSpace(value) == "" {
		return nil
	}
	return strings.Split(value, ",")
}

func (handler *handler) work(writer http.ResponseWriter, request *http.Request) {
	if request.Method != http.MethodGet {
		platform.MethodNotAllowed(writer, http.MethodGet)
		return
	}
	if !fault.ApplyHTTP(writer, request, handler.fault, handler.logger) {
		return
	}

	results := make([]downstreamResult, len(handler.downstreamURLs))
	if handler.callMode == CallParallel {
		var wait sync.WaitGroup
		for index, downstream := range handler.downstreamURLs {
			wait.Add(1)
			go func() {
				defer wait.Done()
				results[index] = handler.call(request, downstream)
			}()
		}
		wait.Wait()
	} else {
		for index, downstream := range handler.downstreamURLs {
			results[index] = handler.call(request, downstream)
		}
	}

	failed := false
	for _, result := range results {
		if result.Error != "" || result.Status < 200 || result.Status >= 300 {
			failed = true
		}
	}
	status := http.StatusOK
	if failed && handler.responsePolicy == ResponsePropagate {
		status = http.StatusBadGateway
	}
	platform.WriteJSON(writer, status, map[string]any{
		"service":     handler.serviceName,
		"call_mode":   handler.callMode,
		"downstreams": results,
	})
}

func (handler *handler) call(request *http.Request, downstream string) downstreamResult {
	result := downstreamResult{URL: downstream + "/work"}
	downstreamRequest, err := platform.NewRequest(request.Context(), http.MethodGet, result.URL)
	if err != nil {
		result.Error = err.Error()
		return result
	}
	response, err := handler.client.Do(downstreamRequest)
	if err != nil {
		result.Error = err.Error()
		return result
	}
	defer response.Body.Close()
	_, _ = io.Copy(io.Discard, io.LimitReader(response.Body, 1<<20))
	result.Status = response.StatusCode
	return result
}
