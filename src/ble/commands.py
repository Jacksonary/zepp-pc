"""
Huami command encoding/decoding for T-Rex 3 / Zepp OS devices.

Commands are sent as byte sequences over BLE GATT characteristics.
The Huami protocol uses a simple packet format:
  [cmd_byte, payload..., checksum]

Where checksum = sum(all bytes before checksum) & 0xFF.

Note: Zepp OS 2.x devices may use a slightly different packet framing.
The commands below are based on the standard Huami protocol used by
Bip/T-Rex/GTR series. If a command doesn't work, the device may
require Zepp OS-specific packet format.

Reference: Gadgetbridge Huami/Amazfit protocol implementation
"""

import logging
import struct
import time
from datetime import datetime

logger = logging.getLogger(__name__)

# ── Huami Command Codes ───────────────────────────────────────────────
# These are standard Huami command codes. Some may differ on Zepp OS 2.x.

CMD_GET_BATTERY = 0x0D
CMD_GET_STEPS = 0x06
CMD_GET_HEART_RATE = 0x15
CMD_FIND_DEVICE = 0x0E
CMD_SET_TIME = 0x0F
CMD_SET_DND = 0x18
CMD_GET_SPO2 = 0x1A
CMD_SET_GOAL = 0x1D


# ── Packet Building ───────────────────────────────────────────────────

def calc_checksum(data: bytes) -> int:
    """Calculate Huami checksum (sum of all bytes, masked to 8-bit)."""
    return sum(data) & 0xFF


def build_command(cmd: int, payload: bytes = b"") -> bytes:
    """Build a complete Huami command packet.

    Format: [cmd, payload..., checksum]
    """
    data = bytes([cmd]) + payload
    return data + bytes([calc_checksum(data)])


def parse_response(data: bytes) -> tuple[int, bytes]:
    """Parse a response packet into (command_code, payload)."""
    if len(data) < 2:
        raise ValueError(f"Response too short: {len(data)} bytes")
    # Last byte is checksum — validate
    expected_ck = calc_checksum(data[:-1])
    actual_ck = data[-1]
    if expected_ck != actual_ck:
        logger.warning(
            f"Checksum mismatch: expected {expected_ck:02x}, got {actual_ck:02x}"
        )
    return data[0], data[1:-1]


# ── Command Builders ──────────────────────────────────────────────────

def get_battery_cmd() -> bytes:
    """Request battery level."""
    return build_command(CMD_GET_BATTERY)


def get_steps_cmd() -> bytes:
    """Request step count."""
    return build_command(CMD_GET_STEPS)


def get_heart_rate_cmd() -> bytes:
    """Request real-time heart rate measurement."""
    return build_command(CMD_GET_HEART_RATE)


def find_device_cmd(duration: int = 3) -> bytes:
    """Make watch vibrate to help locate it.

    Args:
        duration: Vibration duration in seconds (1-10).
    """
    duration = max(1, min(10, duration))
    return build_command(CMD_FIND_DEVICE, bytes([duration]))


def set_time_cmd() -> bytes:
    """Sync current time to the watch.

    Huami protocol uses epoch 2000-01-01 00:00:00 UTC.
    Format: [CMD_SET_TIME, timestamp_4bytes_LE, tz_minutes_2bytes_LE, dow(1), dst(1), checksum]

    Reference: Gadgetbridge HuamiTimeSettingCommand — seconds since 2000-01-01.
    """
    now = datetime.now()
    # Unix timestamp minus the 2000-01-01 epoch offset (946684800)
    huami_ts = int(time.time()) - 946684800

    # Day of week: 0=Sunday, 1=Monday, ..., 6=Saturday
    dow = (now.weekday() + 1) % 7

    # Assume local timezone offset is not needed; send 0 for simplicity
    tz_offset = 0
    dst = 0

    payload = struct.pack("<IhBB", huami_ts, tz_offset, dow, dst)
    return build_command(CMD_SET_TIME, payload)


def set_dnd_cmd(start_h: int, start_m: int, end_h: int, end_m: int, enabled: bool = True) -> bytes:
    """Set Do Not Disturb schedule.

    Format: [CMD_SET_DND, enabled(1), start_h, start_m, end_h, end_m, checksum]
    """
    payload = bytes([
        0x01 if enabled else 0x00,
        start_h, start_m,
        end_h, end_m,
    ])
    return build_command(CMD_SET_DND, payload)


def get_spo2_cmd() -> bytes:
    """Request SpO2 measurement."""
    return build_command(CMD_GET_SPO2)


def set_goal_cmd(steps: int = 10000, calories: int = 500, active_min: int = 30) -> bytes:
    """Set daily activity goals.

    Args:
        steps: Target steps (default 10000)
        calories: Target calories (default 500)
        active_min: Target active minutes (default 30)
    """
    payload = (
        steps.to_bytes(2, "little")
        + calories.to_bytes(2, "little")
        + active_min.to_bytes(2, "little")
    )
    return build_command(CMD_SET_GOAL, payload)


# ── Response Parsers ──────────────────────────────────────────────────

def parse_battery_response(data: bytes) -> int:
    """Parse battery level from response.

    Response format: [CMD_GET_BATTERY, level_percent, checksum]
    """
    cmd, payload = parse_response(data)
    if len(payload) >= 1:
        return payload[0]
    return 0


def parse_steps_response(data: bytes) -> int:
    """Parse step count from response.

    Response format: [CMD_GET_STEPS, steps_low, steps_high, ..., checksum]
    """
    cmd, payload = parse_response(data)
    if len(payload) >= 2:
        return int.from_bytes(payload[:2], byteorder="little")
    return 0


def parse_heart_rate_response(data: bytes) -> int:
    """Parse heart rate from response.

    Response format: [CMD_GET_HEART_RATE, bpm, ..., checksum]
    """
    cmd, payload = parse_response(data)
    if len(payload) >= 1:
        return payload[0]
    return 0


def parse_spo2_response(data: bytes) -> int:
    """Parse SpO2 percentage from response.

    Response format: [CMD_GET_SPO2, spo2_percent, ..., checksum]
    """
    cmd, payload = parse_response(data)
    if len(payload) >= 1:
        return payload[0]
    return 0
