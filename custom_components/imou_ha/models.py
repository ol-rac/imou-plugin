"""Data models for the Imou integration."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum


class DeviceStatus(StrEnum):
    """Device operational status."""

    ACTIVE = "active"
    SLEEPING = "sleeping"
    OFFLINE = "offline"


class CommandState(StrEnum):
    """Command lifecycle state for confirmed-state pattern."""

    IDLE = "idle"
    PENDING = "pending"
    VERIFYING = "verifying"
    CONFIRMED = "confirmed"
    FAILED = "failed"
    TIMEOUT = "timeout"


@dataclass
class ImouDeviceData:
    """Represents a single Imou device's state."""

    serial: str
    name: str
    model: str
    firmware: str
    status: DeviceStatus
    capabilities: set[str] = field(default_factory=set)
    battery_level: int | None = None
    battery_power_source: str = "unknown"
    privacy_enabled: bool | None = None
    motion_detected: bool = False
    human_detected: bool = False
    last_updated: datetime = field(default_factory=datetime.now)
