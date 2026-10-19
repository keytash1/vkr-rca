"""Collection oracle regression only; no model/provider calls."""
import socket
import unittest
from urllib.error import URLError
from urllib.request import urlopen
from r3_context_ablation import validate_capture


class CaptureOracleTests(unittest.TestCase):
    def test_intended_refusal_but_actual_timeout_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'MECHANISM_MISMATCH'):
            validate_capture('connection', [{'status': 503}] * 3,
                             [{'fields': {'error.type': 'TimeoutError'}}] * 3)

    def test_status_and_mechanism_both_required(self):
        records = [{'fields': {'http.response.status_code': 403}}] * 3
        validate_capture('permission', [{'status': 503}] * 3, records)
        with self.assertRaisesRegex(ValueError, 'HTTP_OUTCOME_MISMATCH'):
            validate_capture('permission', [{'status': 200}] * 3, records)

    def test_controls_have_explicit_observed_state(self):
        validate_capture('healthy_unrelated_change', [{'status': 200}] * 3, [])
        validate_capture('unavailable_context', [{'status': 503}] * 3,
                         [{'fields': {'http.response.status_code': 403}}] * 3)

    def test_closed_local_port_gives_actual_connection_refusal(self):
        with socket.socket() as reserved:
            reserved.bind(('127.0.0.1', 0))
            port = reserved.getsockname()[1]
        fields = []
        for _ in range(3):
            with self.assertRaises(URLError) as raised:
                urlopen(f'http://127.0.0.1:{port}/', timeout=.1)
            fields.append({'fields': {'error.type': type(raised.exception.reason).__name__}})
        validate_capture('connection', [{'status': 503}] * 3, fields)


if __name__ == '__main__': unittest.main()
