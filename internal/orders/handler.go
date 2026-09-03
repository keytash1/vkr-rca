package orders

import (
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"log/slog"
	"net/http"
	"net/url"
	"strings"

	"vkr-rca/internal/fault"
	"vkr-rca/internal/platform"
)

const maxResponseBody = 1 << 20

type Config struct {
	PaymentURL string
	Client     *http.Client
	Logger     *slog.Logger
	Fault      *fault.Injector
}

type handler struct {
	paymentURL string
	client     *http.Client
	logger     *slog.Logger
	fault      *fault.Injector
}

type paymentResponse struct {
	Provider string `json:"provider"`
	Status   string `json:"status"`
}

type orderResponse struct {
	OrderID string          `json:"order_id"`
	Status  string          `json:"status"`
	Payment paymentResponse `json:"payment"`
}

func NewHandler(config Config) (http.Handler, error) {
	if config.Client == nil {
		return nil, errors.New("HTTP client is required")
	}
	if config.Logger == nil {
		return nil, errors.New("logger is required")
	}
	if config.Fault == nil {
		return nil, errors.New("fault injector is required")
	}
	if err := validateURL(config.PaymentURL); err != nil {
		return nil, fmt.Errorf("payment URL: %w", err)
	}

	handler := &handler{
		paymentURL: strings.TrimRight(config.PaymentURL, "/"),
		client:     config.Client,
		logger:     config.Logger,
		fault:      config.Fault,
	}

	mux := http.NewServeMux()
	mux.HandleFunc("/health", platform.HealthHandler("orders"))
	mux.HandleFunc("/orders/current", handler.currentOrder)
	mux.Handle("/debug/", fault.NewHandler(config.Fault))
	return platform.Middleware(config.Logger, mux), nil
}

func (handler *handler) currentOrder(writer http.ResponseWriter, request *http.Request) {
	if request.Method != http.MethodGet {
		platform.MethodNotAllowed(writer, http.MethodGet)
		return
	}
	if !fault.ApplyHTTP(writer, request, handler.fault, handler.logger) {
		return
	}

	downstreamRequest, err := platform.NewRequest(
		request.Context(),
		http.MethodGet,
		handler.paymentURL+"/payments/authorize",
	)
	if err != nil {
		platform.WriteJSON(writer, http.StatusInternalServerError, map[string]string{"error": "cannot create payment request"})
		return
	}

	response, err := handler.client.Do(downstreamRequest)
	if err != nil {
		platform.WriteJSON(writer, http.StatusBadGateway, map[string]string{"error": "payment service unavailable"})
		return
	}
	defer response.Body.Close()

	if response.StatusCode != http.StatusOK {
		platform.WriteJSON(writer, http.StatusBadGateway, map[string]string{"error": "payment service returned an error"})
		return
	}

	var payment paymentResponse
	decoder := json.NewDecoder(io.LimitReader(response.Body, maxResponseBody))
	if err := decoder.Decode(&payment); err != nil {
		platform.WriteJSON(writer, http.StatusBadGateway, map[string]string{"error": "invalid payment response"})
		return
	}

	platform.WriteJSON(writer, http.StatusOK, orderResponse{
		OrderID: "demo-order",
		Status:  "confirmed",
		Payment: payment,
	})
}

func validateURL(value string) error {
	parsed, err := url.ParseRequestURI(value)
	if err != nil {
		return err
	}
	if parsed.Scheme != "http" && parsed.Scheme != "https" {
		return errors.New("scheme must be http or https")
	}
	if parsed.Host == "" {
		return errors.New("host is required")
	}
	return nil
}
