"""Device data models."""
from dataclasses import dataclass
from typing import Optional


@dataclass
class DeviceInfo:
    name: str
    mac: str
    model: str = ""
    firmware_version: str = ""
    serial_number: str = ""
    battery_level: int = 0
    hardware_version: str = ""


@dataclass
class ConnectionState:
    connected: bool = False
    authenticated: bool = False
    device_info: Optional[DeviceInfo] = None
    error: Optional[str] = None
