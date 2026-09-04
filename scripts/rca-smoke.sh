#!/bin/sh
set -eu

gateway_port="${GATEWAY_PORT:-18080}"
orders_port="${ORDERS_PORT:-8081}"
payment_port="${PAYMENT_PORT:-8082}"
rca_port="${RCA_HTTP_PORT:-18090}"

reset_faults() {
	curl --fail --silent --show-error --request POST "http://localhost:${gateway_port}/debug/reset" >/dev/null
	curl --fail --silent --show-error --request POST "http://localhost:${orders_port}/debug/reset" >/dev/null
	curl --fail --silent --show-error --request POST "http://localhost:${payment_port}/debug/reset" >/dev/null
}

reset_current() {
	reset_faults
	curl --fail --silent --show-error --request POST "http://localhost:${rca_port}/debug/anomaly/reset" >/dev/null
}

set_fault() {
	port="$1"
	payload="$2"
	curl --fail --silent --show-error \
		--header 'Content-Type: application/json' \
		--data "$payload" \
		"http://localhost:${port}/debug/fault" >/dev/null
}

send_successes() {
	label="$1"
	for request in $(seq 1 20); do
		curl --fail --silent --show-error \
			--header "X-Request-ID: rca-${label}-${request}" \
			"http://localhost:${gateway_port}/api/order" >/dev/null
	done
}

send_failures() {
	label="$1"
	expected_status="$2"
	for request in $(seq 1 20); do
		http_code=$(curl --silent --show-error --output /dev/null --write-out '%{http_code}' \
			--header "X-Request-ID: rca-${label}-${request}" \
			"http://localhost:${gateway_port}/api/order")
		test "$http_code" = "$expected_status"
	done
}

wait_result() {
	label="$1"
	primary="$2"
	observed="$3"
	expected_top="$4"
	rca_file="/tmp/vkr-rca-m6-${label}-rca.json"
	features_file="/tmp/vkr-rca-m6-${label}-features.json"
	for attempt in $(seq 1 30); do
		curl --fail --silent --show-error "http://localhost:${rca_port}/api/rca" --output "$rca_file"
		if grep --quiet "\"state\":\"ready\"" "$rca_file" && \
			grep --quiet "\"primary_signal\":\"${primary}\"" "$rca_file" && \
			grep --fixed-strings --quiet "\"observed_anomalies\":${observed}" "$rca_file" && \
			grep --fixed-strings --quiet "\"hybrid_v1\":[{\"rank\":1,\"service\":\"${expected_top}\"" "$rca_file"; then
			curl --fail --silent --show-error "http://localhost:${rca_port}/api/features" --output "$features_file"
			grep --quiet '"feature_schema_version":"m6-v1"' "$features_file"
			grep --quiet '"topology_source":"active_traces"' "$features_file"
			if grep -E 'NaN|Inf|ground_truth|fault_service|probability|confidence' "$rca_file" "$features_file" >/dev/null; then
				echo "forbidden diagnostic output in ${label}" >&2
				exit 1
			fi
			echo "${label}:"
			cat "$features_file"
			echo
			cat "$rca_file"
			echo
			return 0
		fi
		sleep 1
	done
	cat "$rca_file" >&2
	return 1
}

wait_healthy() {
	rca_file="/tmp/vkr-rca-m6-healthy-rca.json"
	for attempt in $(seq 1 30); do
		curl --fail --silent --show-error "http://localhost:${rca_port}/api/rca" --output "$rca_file"
		if grep --quiet '"state":"no_anomaly"' "$rca_file" && \
			grep --fixed-strings --quiet '"hybrid_v1":[]' "$rca_file"; then
			echo "healthy:"
			cat "$rca_file"
			echo
			return 0
		fi
		sleep 1
	done
	cat "$rca_file" >&2
	return 1
}

run_latency() {
	label="$1"
	port="$2"
	observed="$3"
	root="$4"
	reset_current
	set_fault "$port" '{"latency_ms":700,"error_rate":0}'
	send_successes "$label"
	reset_faults
	wait_result "$label" latency "$observed" "$root"
}

run_error() {
	label="$1"
	port="$2"
	status="$3"
	observed="$4"
	root="$5"
	reset_current
	set_fault "$port" '{"latency_ms":0,"error_rate":1}'
	send_failures "$label" "$status"
	reset_faults
	wait_result "$label" error "$observed" "$root"
}

trap 'reset_faults >/dev/null 2>&1 || true' EXIT

reset_current
send_successes healthy
wait_healthy

run_latency payment-latency "$payment_port" '["gateway","orders","payment"]' payment
run_latency orders-latency "$orders_port" '["gateway","orders"]' orders
run_latency gateway-latency "$gateway_port" '["gateway"]' gateway

run_error payment-error "$payment_port" 502 '["gateway","orders","payment"]' payment
run_error orders-error "$orders_port" 502 '["gateway","orders"]' orders
run_error gateway-error "$gateway_port" 500 '["gateway"]' gateway

reset_faults
