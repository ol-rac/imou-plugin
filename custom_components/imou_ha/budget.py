"""API budget tracking for the Imou integration (Phase 5, D-01 through D-04)."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime

BUDGET_STORAGE_KEY = "api_budget"


@dataclass
class ImouBudgetState:
    """Tracks Imou API call counts for budget management and throttle decisions.

    Shared between ImouApiClient (increments on each call) and ImouCoordinator
    (reads for throttle decisions and persists to config entry).

    Counter structure:
      - calls_today: resets at UTC midnight each day
      - calls_this_month: resets on the 1st of each month
      - day_reset_date: YYYY-MM-DD — the date when calls_today was last reset
      - month_reset_date: YYYY-MM — the month when calls_this_month was last reset
      - day_start_time: ISO datetime of the last daily reset, used for burn rate calculation
    """

    calls_today: int = 0
    calls_this_month: int = 0
    day_reset_date: str = ""  # YYYY-MM-DD ISO format
    month_reset_date: str = ""  # YYYY-MM format
    day_start_time: str = ""  # ISO datetime for burn rate calculation

    def increment(self, now: datetime) -> None:
        """Increment API call counters, applying daily/monthly resets as needed.

        Call this BEFORE the actual API call so that even failed calls are counted
        (Imou cloud counts the call regardless of the response).

        Args:
            now: Current UTC datetime to check boundary conditions.

        """
        today_str = now.strftime("%Y-%m-%d")
        month_str = now.strftime("%Y-%m")

        # Check day boundary — reset calls_today if a new day has started
        if self.day_reset_date != today_str:
            self.calls_today = 0
            self.day_reset_date = today_str
            self.day_start_time = now.isoformat()

        # Check month boundary — reset calls_this_month if a new month has started
        if self.month_reset_date != month_str:
            self.calls_this_month = 0
            self.month_reset_date = month_str

        # Increment both counters
        self.calls_today += 1
        self.calls_this_month += 1

    def projected_daily_rate(self, now: datetime) -> float:
        """Calculate projected calls per day based on observed burn rate.

        Args:
            now: Current UTC datetime.

        Returns:
            Projected daily call count. Returns float(calls_today) if less than
            0.01 hours have elapsed since day start (avoids division by near-zero).

        """
        if not self.day_start_time:
            return float(self.calls_today)

        try:
            start = datetime.fromisoformat(self.day_start_time)
        except ValueError:
            return float(self.calls_today)

        elapsed = (now - start).total_seconds() / 3600
        if elapsed < 0.01:
            return float(self.calls_today)
        return (self.calls_today / elapsed) * 24

    def to_dict(self) -> dict:
        """Serialize budget state to a JSON-compatible dict for config entry storage."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> ImouBudgetState:
        """Deserialize budget state from a config entry dict.

        Missing keys fall back to field defaults, enabling safe upgrades from
        older integration versions that did not store budget state.

        Args:
            data: Dict as retrieved from config entry data, may be empty or partial.

        Returns:
            ImouBudgetState with any missing fields set to defaults.

        """
        defaults = cls()
        return cls(**{k: data.get(k, v) for k, v in defaults.__dict__.items()})
