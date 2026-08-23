package gateway

import (
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"log/slog"
	"net/http"
	"net/url"
	"strings"

	"vkr-rca/internal/platform"
)

const maxResponseBody = 1 << 20

type Config struct {
	OrdersURL string
	Client    *http.Client
	Logger    *slog.Logger
}

type handler struct {
	ordersURL string
	client    *http.Client
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

type gatewayResponse struct {
	Service string        `json:"service"`
	Order   orderResponse `json:"order"`
}

func NewHandler(config Config) (http.Handler, error) {
	if config.Client == nil {
		return nil, errors.New("HTTP client is required")
	}
	if config.Logger == nil {
		return nil, errors.New("logger is required")
	}
	if err := validateURL(config.OrdersURL); err != nil {
		return nil, fmt.Errorf("orders URL: %w", err)
	}

	handler := &handler{
		ordersURL: strings.TrimRight(config.OrdersURL, "/"),
		client:    config.Client,
	}

	mux := http.NewServeMux()
	mux.HandleFunc("/health", platform.HealthHandler("gateway"))
	mux.HandleFunc("/api/order", handler.order)
	return platform.Middleware(config.Logger, mux), nil
}

func (handler *handler) order(writer http.ResponseWriter, request *http.Request) {
	if request.Method != http.MethodGet {
		platform.MethodNotAllowed(writer, http.MethodGet)
		return
	}

	downstreamRequest, err := platform.NewRequest(
		request.Context(),
		http.MethodGet,
		handler.ordersURL+"/orders/current",
	)
	if err != nil {
		platform.WriteJSON(writer, http.StatusInternalServerError, map[string]string{"error": "cannot create orders request"})
		return
	}

	response, err := handler.client.Do(downstreamRequest)
	if err != nil {
		platform.WriteJSON(writer, http.StatusBadGateway, map[string]string{"error": "orders service unavailable"})
		return
	}
	defer response.Body.Close()

	if response.StatusCode != http.StatusOK {
		platform.WriteJSON(writer, http.StatusBadGateway, map[string]string{"error": "orders service returned an error"})
		return
	}

	var order orderResponse
	decoder := json.NewDecoder(io.LimitReader(response.Body, maxResponseBody))
	if err := decoder.Decode(&order); err != nil {
		platform.WriteJSON(writer, http.StatusBadGateway, map[string]string{"error": "invalid orders response"})
		return
	}

	platform.WriteJSON(writer, http.StatusOK, gatewayResponse{
		Service: "gateway",
		Order:   order,
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
