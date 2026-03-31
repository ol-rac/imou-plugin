"""Tests for ImouBudgetState and API client budget instrumentation."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest

from custom_components.imou_ha.api_client import ImouApiClient
from custom_components.imou_ha.budget import ImouBudgetState

# ---------------------------------------------------------------------------
# ImouBudgetState — initial state
# ---------------------------------------------------------------------------


class TestImouBudgetStateInit:
    def test_starts_with_zero_calls_today(self) -> None:
        """ImouBudgetState() starts with calls_today=0."""
        state = ImouBudgetState()
        assert state.calls_today == 0

    def test_starts_with_zero_calls_this_month(self) -> None:
        """ImouBudgetState() starts with calls_this_month=0."""
        state = ImouBudgetState()
        assert state.calls_this_month == 0


# ---------------------------------------------------------------------------
# ImouBudgetState — increment()
# ---------------------------------------------------------------------------


class TestImouBudgetStateIncrement:
    def test_increment_increases_calls_today(self) -> None:
        """increment() increases calls_today by 1."""
        state = ImouBudgetState()
        now = datetime(2026, 3, 30, 12, 0, 0, tzinfo=UTC)
        state.increment(now)
        assert state.calls_today == 1

    def test_increment_increases_calls_this_month(self) -> None:
        """increment() increases calls_this_month by 1."""
        state = ImouBudgetState()
        now = datetime(2026, 3, 30, 12, 0, 0, tzinfo=UTC)
        state.increment(now)
        assert state.calls_this_month == 1

    def test_increment_twice_results_in_two(self) -> None:
        """Two increments result in both counters at 2."""
        state = ImouBudgetState()
        now = datetime(2026, 3, 30, 12, 0, 0, tzinfo=UTC)
        state.increment(now)
        state.increment(now)
        assert state.calls_today == 2
        assert state.calls_this_month == 2

    def test_day_reset_resets_calls_today_to_1(self) -> None:
        """increment() resets calls_today to 1 when day_reset_date differs from today."""
        state = ImouBudgetState(
            calls_today=50,
            calls_this_month=1000,
            day_reset_date="2026-03-29",
            month_reset_date="2026-03",
            day_start_time="2026-03-29T08:00:00+00:00",
        )
        now = datetime(2026, 3, 30, 8, 0, 0, tzinfo=UTC)
        state.increment(now)
        assert state.calls_today == 1

    def test_day_reset_does_not_reset_calls_this_month(self) -> None:
        """Day reset does not reset monthly counter."""
        state = ImouBudgetState(
            calls_today=50,
            calls_this_month=1000,
            day_reset_date="2026-03-29",
            month_reset_date="2026-03",
            day_start_time="2026-03-29T08:00:00+00:00",
        )
        now = datetime(2026, 3, 30, 8, 0, 0, tzinfo=UTC)
        state.increment(now)
        assert state.calls_this_month == 1001

    def test_month_reset_resets_calls_this_month_to_1(self) -> None:
        """increment() resets calls_this_month to 1 when month_reset_date differs from current month."""
        state = ImouBudgetState(
            calls_today=50,
            calls_this_month=25000,
            day_reset_date="2026-04-01",
            month_reset_date="2026-03",
            day_start_time="2026-04-01T00:00:00+00:00",
        )
        now = datetime(2026, 4, 1, 0, 0, 0, tzinfo=UTC)
        state.increment(now)
        assert state.calls_this_month == 1

    def test_month_reset_also_resets_day_calls(self) -> None:
        """Month reset implies day reset too when day_reset_date is stale."""
        state = ImouBudgetState(
            calls_today=50,
            calls_this_month=25000,
            day_reset_date="2026-03-31",
            month_reset_date="2026-03",
            day_start_time="2026-03-31T00:00:00+00:00",
        )
        now = datetime(2026, 4, 1, 0, 0, 0, tzinfo=UTC)
        state.increment(now)
        assert state.calls_today == 1

    def test_increment_sets_day_start_time_on_day_reset(self) -> None:
        """increment() sets day_start_time when day resets."""
        state = ImouBudgetState(
            calls_today=10,
            calls_this_month=100,
            day_reset_date="2026-03-29",
            month_reset_date="2026-03",
            day_start_time="2026-03-29T08:00:00+00:00",
        )
        now = datetime(2026, 3, 30, 9, 30, 0, tzinfo=UTC)
        state.increment(now)
        assert state.day_start_time == now.isoformat()

    def test_increment_updates_day_reset_date(self) -> None:
        """increment() updates day_reset_date to today's date string."""
        state = ImouBudgetState(
            calls_today=10,
            calls_this_month=100,
            day_reset_date="2026-03-29",
            month_reset_date="2026-03",
            day_start_time="2026-03-29T08:00:00+00:00",
        )
        now = datetime(2026, 3, 30, 9, 30, 0, tzinfo=UTC)
        state.increment(now)
        assert state.day_reset_date == "2026-03-30"

    def test_increment_updates_month_reset_date(self) -> None:
        """increment() updates month_reset_date on month boundary."""
        state = ImouBudgetState(
            calls_today=50,
            calls_this_month=25000,
            day_reset_date="2026-04-01",
            month_reset_date="2026-03",
            day_start_time="2026-04-01T00:00:00+00:00",
        )
        now = datetime(2026, 4, 1, 0, 0, 0, tzinfo=UTC)
        state.increment(now)
        assert state.month_reset_date == "2026-04"


# ---------------------------------------------------------------------------
# ImouBudgetState — projected_daily_rate()
# ---------------------------------------------------------------------------


class TestProjectedDailyRate:
    def test_returns_calls_today_when_elapsed_tiny(self) -> None:
        """projected_daily_rate() returns float(calls_today) when elapsed < 0.01 hours."""
        state = ImouBudgetState(
            calls_today=5,
            calls_this_month=5,
            day_reset_date="2026-03-30",
            month_reset_date="2026-03",
            day_start_time="2026-03-30T12:00:00+00:00",
        )
        now = datetime(2026, 3, 30, 12, 0, 30, tzinfo=UTC)  # 30 seconds later ~ 0.0083 hours
        assert state.projected_daily_rate(now) == 5.0

    def test_returns_projected_rate_for_normal_elapsed(self) -> None:
        """projected_daily_rate() returns (calls_today / elapsed_hours) * 24."""
        state = ImouBudgetState(
            calls_today=10,
            calls_this_month=10,
            day_reset_date="2026-03-30",
            month_reset_date="2026-03",
            day_start_time="2026-03-30T00:00:00+00:00",
        )
        now = datetime(2026, 3, 30, 2, 0, 0, tzinfo=UTC)  # 2 hours later
        # rate = (10 / 2) * 24 = 120
        expected = (10 / 2) * 24
        assert state.projected_daily_rate(now) == pytest.approx(expected)

    def test_returns_zero_rate_when_no_calls_yet(self) -> None:
        """projected_daily_rate() returns 0.0 when calls_today=0."""
        state = ImouBudgetState(
            calls_today=0,
            calls_this_month=0,
            day_reset_date="2026-03-30",
            month_reset_date="2026-03",
            day_start_time="2026-03-30T00:00:00+00:00",
        )
        now = datetime(2026, 3, 30, 6, 0, 0, tzinfo=UTC)
        assert state.projected_daily_rate(now) == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# ImouBudgetState — serialization
# ---------------------------------------------------------------------------


class TestImouBudgetStateSerialization:
    def test_to_dict_round_trips_with_from_dict(self) -> None:
        """to_dict() round-trips with from_dict()."""
        state = ImouBudgetState(
            calls_today=42,
            calls_this_month=1234,
            day_reset_date="2026-03-30",
            month_reset_date="2026-03",
            day_start_time="2026-03-30T08:00:00+00:00",
        )
        serialized = state.to_dict()
        restored = ImouBudgetState.from_dict(serialized)
        assert restored.calls_today == 42
        assert restored.calls_this_month == 1234
        assert restored.day_reset_date == "2026-03-30"
        assert restored.month_reset_date == "2026-03"
        assert restored.day_start_time == "2026-03-30T08:00:00+00:00"

    def test_from_dict_empty_returns_zeroed_state(self) -> None:
        """from_dict({}) returns fresh zeroed state (upgrade path)."""
        state = ImouBudgetState.from_dict({})
        assert state.calls_today == 0
        assert state.calls_this_month == 0
        assert state.day_reset_date == ""
        assert state.month_reset_date == ""
        assert state.day_start_time == ""

    def test_from_dict_partial_uses_defaults(self) -> None:
        """from_dict with partial keys falls back to field defaults."""
        state = ImouBudgetState.from_dict({"calls_today": 5})
        assert state.calls_today == 5
        assert state.calls_this_month == 0  # default


# ---------------------------------------------------------------------------
# ImouApiClient — budget instrumentation
# ---------------------------------------------------------------------------


APP_ID = "test_app_id"
APP_SECRET = "test_app_secret"
API_URL = "openapi-fk.easy4ip.com"


def _make_client_with_budget() -> tuple[ImouApiClient, ImouBudgetState]:
    budget = ImouBudgetState()
    with patch("custom_components.imou_ha.api_client.ImouOpenApiClient"):
        client = ImouApiClient(APP_ID, APP_SECRET, API_URL, budget_state=budget)
    return client, budget


def _make_client_without_budget() -> ImouApiClient:
    with patch("custom_components.imou_ha.api_client.ImouOpenApiClient"):
        return ImouApiClient(APP_ID, APP_SECRET, API_URL)


class TestApiClientBudgetInstrumentation:
    async def test_get_devices_increments_budget(self) -> None:
        """async_get_devices increments budget counter."""
        client, budget = _make_client_with_budget()
        # Mock device manager
        mock_dm = AsyncMock()
        mock_dm.async_get_devices = AsyncMock(return_value=[])
        with patch("custom_components.imou_ha.api_client.ImouDeviceManager", return_value=mock_dm):
            await client.async_get_devices()
        assert budget.calls_this_month == 1

    async def test_get_device_online_status_increments_budget(self) -> None:
        """async_get_device_online_status increments budget counter."""
        client, budget = _make_client_with_budget()
        mock_dm = AsyncMock()
        mock_dm.async_get_device_online_status = AsyncMock(
            return_value={"onLine": "1"},
        )
        client._device_manager = mock_dm
        await client.async_get_device_online_status("DEVICE123")
        assert budget.calls_this_month == 1

    async def test_validate_credentials_increments_budget(self) -> None:
        """async_validate_credentials increments budget counter."""
        client, budget = _make_client_with_budget()
        client._client.async_get_token = AsyncMock(return_value=None)
        await client.async_validate_credentials()
        assert budget.calls_this_month == 1

    async def test_get_device_power_info_increments_budget(self) -> None:
        """async_get_device_power_info increments budget counter."""
        client, budget = _make_client_with_budget()
        mock_dm = AsyncMock()
        mock_dm.async_get_device_power_info = AsyncMock(
            return_value={"electricitys": []},
        )
        client._device_manager = mock_dm
        await client.async_get_device_power_info("DEVICE123")
        assert budget.calls_this_month == 1

    async def test_get_alarm_status_increments_budget(self) -> None:
        """async_get_alarm_status increments budget counter."""
        client, budget = _make_client_with_budget()
        client._client.async_request_api = AsyncMock(return_value={"alarms": []})
        await client.async_get_alarm_status("DEVICE123", "2026-03-30 00:00:00", "2026-03-30 01:00:00")
        assert budget.calls_this_month == 1

    async def test_multiple_calls_accumulate_count(self) -> None:
        """Multiple API calls accumulate in budget counter."""
        client, budget = _make_client_with_budget()
        client._client.async_get_token = AsyncMock(return_value=None)
        client._client.async_request_api = AsyncMock(return_value={"alarms": []})
        await client.async_validate_credentials()
        await client.async_get_alarm_status("DEVICE123", "2026-03-30 00:00:00", "2026-03-30 01:00:00")
        assert budget.calls_this_month == 2

    async def test_budget_none_does_not_error(self) -> None:
        """ImouApiClient with budget_state=None does not error on API calls."""
        client = _make_client_without_budget()
        client._client.async_get_token = AsyncMock(return_value=None)
        # Should not raise
        await client.async_validate_credentials()

    async def test_budget_increments_before_api_call_even_on_error(self) -> None:
        """Budget increments BEFORE the API call, even if the call raises."""
        from pyimouapi.exceptions import ImouException

        client, budget = _make_client_with_budget()
        client._client.async_get_token = AsyncMock(side_effect=ImouException("API down"))
        with pytest.raises(Exception):  # noqa: B017
            await client.async_validate_credentials()
        # Counter should still be incremented
        assert budget.calls_this_month == 1
