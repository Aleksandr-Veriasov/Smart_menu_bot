"""Тесты classify_failure и backoff_seconds из broadcast_sender."""

from packages.services.broadcast_sender import (
    FailureKind,
    backoff_seconds,
    classify_failure,
)


class TestClassifyFailurePermanent:
    def test_403_is_permanent(self) -> None:
        resp = {"ok": False, "error_code": 403, "description": "Forbidden: bot was blocked by the user"}
        kind, retry_after = classify_failure(resp)
        assert kind == FailureKind.permanent
        assert retry_after is None

    def test_400_is_permanent(self) -> None:
        resp = {"ok": False, "error_code": 400, "description": "Bad Request: chat not found"}
        kind, retry_after = classify_failure(resp)
        assert kind == FailureKind.permanent
        assert retry_after is None

    def test_user_deactivated_is_permanent(self) -> None:
        resp = {
            "ok": False,
            "error_code": 403,
            "description": "Forbidden: user is deactivated",
        }
        kind, _ = classify_failure(resp)
        assert kind == FailureKind.permanent

    def test_bot_blocked_is_permanent(self) -> None:
        resp = {"ok": False, "error_code": 403, "description": "Forbidden: bot was blocked by the user"}
        kind, _ = classify_failure(resp)
        assert kind == FailureKind.permanent


class TestClassifyFailureRetry:
    def test_429_is_retry_with_retry_after(self) -> None:
        resp = {
            "ok": False,
            "error_code": 429,
            "description": "Too Many Requests: retry after 42",
            "parameters": {"retry_after": 42},
        }
        kind, retry_after = classify_failure(resp)
        assert kind == FailureKind.retry
        assert retry_after == 42.0

    def test_429_without_parameters_defaults_to_30s(self) -> None:
        resp = {"ok": False, "error_code": 429, "description": "Too Many Requests: retry after 30"}
        kind, retry_after = classify_failure(resp)
        assert kind == FailureKind.retry
        assert retry_after == 30.0

    def test_500_is_retry(self) -> None:
        resp = {"ok": False, "error_code": 500, "description": "Internal Server Error"}
        kind, retry_after = classify_failure(resp)
        assert kind == FailureKind.retry
        assert retry_after is None

    def test_502_is_retry(self) -> None:
        resp = {"ok": False, "error_code": 502, "description": "Bad Gateway"}
        kind, retry_after = classify_failure(resp)
        assert kind == FailureKind.retry


class TestBackoff:
    def test_first_attempt_is_base(self) -> None:
        value = backoff_seconds(1)
        assert 30.0 <= value <= 35.0

    def test_second_attempt_is_double(self) -> None:
        value = backoff_seconds(2)
        assert 60.0 <= value <= 65.0

    def test_third_attempt_is_quadruple(self) -> None:
        value = backoff_seconds(3)
        assert 120.0 <= value <= 125.0

    def test_backoff_increases_with_attempt(self) -> None:
        values = [backoff_seconds(n) for n in range(1, 5)]
        for i in range(len(values) - 1):
            # Base grows 2x per attempt; even with max jitter the ordering holds
            assert values[i] < values[i + 1]

    def test_backoff_capped_at_max(self) -> None:
        # attempt=8 → base=30*128=3840 → capped at 3600
        value = backoff_seconds(8)
        assert value <= 3600.0 + 5.0  # max + jitter
