GATEWAY_PORT ?= 18080
ORDERS_PORT ?= 8081
PAYMENT_PORT ?= 8082
JAEGER_UI_PORT ?= 16686
RCA_HTTP_PORT ?= 18090

.PHONY: fmt test build compose-up compose-down smoke trace-smoke graph-smoke fault-payment-latency fault-orders-latency fault-payment-errors fault-reset fault-status logs

fmt:
	gofmt -w cmd internal

test:
	go test ./...

build:
	go build ./...

compose-up:
	docker compose up --build -d --wait

compose-down:
	docker compose down --remove-orphans

smoke:
	curl --fail --silent --show-error \
		--header 'X-Request-ID: manual-smoke' \
		http://localhost:$(GATEWAY_PORT)/api/order

trace-smoke:
	curl --fail --silent --show-error \
		--header 'X-Request-ID: milestone-2-smoke' \
		http://localhost:$(GATEWAY_PORT)/api/order
	@echo
	@echo "Open Jaeger: http://localhost:$(JAEGER_UI_PORT)"

graph-smoke:
	curl --fail --silent --show-error --request POST http://localhost:$(RCA_HTTP_PORT)/debug/reset
	@echo
	@$(MAKE) --no-print-directory fault-reset
	@for request in 1 2 3 4 5 6 7 8 9 10; do \
		curl --fail --silent --show-error \
			--header "X-Request-ID: graph-smoke-$$request" \
			http://localhost:$(GATEWAY_PORT)/api/order >/dev/null || exit 1; \
	done
	@for attempt in 1 2 3 4 5 6 7 8 9 10; do \
		curl --fail --silent --show-error \
			http://localhost:$(RCA_HTTP_PORT)/api/graph \
			--output /tmp/vkr-rca-graph-smoke.json || exit 1; \
		if grep --quiet '"source":"gateway","target":"orders","observations":10' /tmp/vkr-rca-graph-smoke.json && \
			grep --quiet '"source":"orders","target":"payment","observations":10' /tmp/vkr-rca-graph-smoke.json; then \
			cat /tmp/vkr-rca-graph-smoke.json; echo; exit 0; \
		fi; \
		sleep 1; \
	done; \
	cat /tmp/vkr-rca-graph-smoke.json; echo; exit 1

fault-payment-latency:
	curl --fail --silent --show-error \
		--header 'Content-Type: application/json' \
		--data '{"latency_ms":700,"error_rate":0}' \
		http://localhost:$(PAYMENT_PORT)/debug/fault

fault-orders-latency:
	curl --fail --silent --show-error \
		--header 'Content-Type: application/json' \
		--data '{"latency_ms":700,"error_rate":0}' \
		http://localhost:$(ORDERS_PORT)/debug/fault

fault-payment-errors:
	curl --fail --silent --show-error \
		--header 'Content-Type: application/json' \
		--data '{"latency_ms":0,"error_rate":0.5}' \
		http://localhost:$(PAYMENT_PORT)/debug/fault

fault-reset:
	curl --fail --silent --show-error --request POST http://localhost:$(ORDERS_PORT)/debug/reset
	@echo
	curl --fail --silent --show-error --request POST http://localhost:$(PAYMENT_PORT)/debug/reset
	@echo

fault-status:
	@echo "Orders:"
	@curl --fail --silent --show-error http://localhost:$(ORDERS_PORT)/debug/fault
	@echo "Payment:"
	@curl --fail --silent --show-error http://localhost:$(PAYMENT_PORT)/debug/fault

logs:
	docker compose logs --follow
