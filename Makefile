GATEWAY_PORT ?= 18080
JAEGER_UI_PORT ?= 16686

.PHONY: fmt test build compose-up compose-down smoke trace-smoke logs

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

logs:
	docker compose logs --follow
