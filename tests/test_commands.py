"""Tests for Huami command encoding/decoding."""

from src.ble import commands as cmds


def test_calc_checksum():
    assert cmds.calc_checksum(bytes([0x0D])) == 0x0D
    assert cmds.calc_checksum(bytes([0x01, 0x02])) == 0x03
    assert cmds.calc_checksum(bytes([0xFF, 0x01])) == 0x00


def test_build_command():
    cmd = cmds.build_command(0x0D)
    assert cmd == bytes([0x0D, 0x0D])  # cmd + checksum

    cmd = cmds.build_command(0x10, bytes([0x01]))
    expected = bytes([0x10, 0x01, 0x11])
    assert cmd == expected


def test_parse_response():
    data = bytes([0x0D, 0x50, 0x5D])  # battery 80%
    c, payload = cmds.parse_response(data)
    assert c == 0x0D
    assert payload == bytes([0x50])

    # checksum mismatch should still parse but warn
    data_bad = bytes([0x0D, 0x50, 0xFF])
    c, payload = cmds.parse_response(data_bad)
    assert c == 0x0D
    assert payload == bytes([0x50])


# ── Battery ──────────────────────────────────────────────────────────

def test_get_battery_cmd():
    cmd = cmds.get_battery_cmd()
    assert cmd[0] == cmds.CMD_GET_BATTERY
    assert cmd[-1] == cmds.calc_checksum(cmd[:-1])


def test_parse_battery_response():
    data = bytes([0x0D, 0x50, 0x5D])
    assert cmds.parse_battery_response(data) == 0x50  # 80%

    data_full = bytes([0x0D, 0x64, 0x71])
    assert cmds.parse_battery_response(data_full) == 100  # 100%


# ── Steps ────────────────────────────────────────────────────────────

def test_get_steps_cmd():
    cmd = cmds.get_steps_cmd()
    assert cmd[0] == cmds.CMD_GET_STEPS
    assert cmd[-1] == cmds.calc_checksum(cmd[:-1])


def test_parse_steps_response():
    data = bytes([0x06, 0xE8, 0x03, 0xEB])  # 1000 steps (0x03E8)
    assert cmds.parse_steps_response(data) == 1000

    data_zero = bytes([0x06, 0x00, 0x00, 0x06])
    assert cmds.parse_steps_response(data_zero) == 0


# ── Heart Rate ───────────────────────────────────────────────────────

def test_get_heart_rate_cmd():
    cmd = cmds.get_heart_rate_cmd()
    assert cmd[0] == cmds.CMD_GET_HEART_RATE
    assert cmd[-1] == cmds.calc_checksum(cmd[:-1])


def test_parse_heart_rate_response():
    data = bytes([0x15, 0x4B, 0x60])  # 75 bpm
    assert cmds.parse_heart_rate_response(data) == 75


# ── Find Device ──────────────────────────────────────────────────────

def test_find_device_cmd():
    cmd = cmds.find_device_cmd()
    assert cmd[0] == cmds.CMD_FIND_DEVICE
    assert cmd[-1] == cmds.calc_checksum(cmd[:-1])
    # payload is duration (3 seconds)
    assert cmd[1] == 3


def test_find_device_cmd_custom_duration():
    cmd = cmds.find_device_cmd(duration=5)
    assert cmd[1] == 5


# ── SpO2 ─────────────────────────────────────────────────────────────

def test_get_spo2_cmd():
    cmd = cmds.get_spo2_cmd()
    assert cmd[0] == cmds.CMD_GET_SPO2
    assert cmd[-1] == cmds.calc_checksum(cmd[:-1])


def test_parse_spo2_response():
    data = bytes([0x1A, 0x62, 0x7C])  # 98%
    assert cmds.parse_spo2_response(data) == 0x62  # 98%


# ── Set Time ─────────────────────────────────────────────────────────

def test_set_time_cmd():
    cmd = cmds.set_time_cmd()
    assert cmd[0] == cmds.CMD_SET_TIME
    assert cmd[-1] == cmds.calc_checksum(cmd[:-1])
    # Should have: timestamp(4) + tz(2) + dow(1) + dst(1) = 8 bytes payload
    assert len(cmd) == 10  # 1 cmd + 8 payload + 1 checksum


# ── DND ──────────────────────────────────────────────────────────────

def test_set_dnd_cmd():
    cmd = cmds.set_dnd_cmd(22, 0, 7, 0, enabled=True)
    assert cmd[0] == cmds.CMD_SET_DND
    assert cmd[1] == 0x01  # enabled
    assert cmd[-1] == cmds.calc_checksum(cmd[:-1])

    cmd_off = cmds.set_dnd_cmd(0, 0, 0, 0, enabled=False)
    assert cmd_off[1] == 0x00  # disabled


# ── Goals ────────────────────────────────────────────────────────────

def test_set_goal_cmd():
    cmd = cmds.set_goal_cmd(steps=10000, calories=500, active_min=30)
    assert cmd[0] == cmds.CMD_SET_GOAL
    assert cmd[-1] == cmds.calc_checksum(cmd[:-1])
    # payload: steps(2) + calories(2) + active_min(2) = 6 bytes
    assert len(cmd) == 8  # 1 cmd + 6 payload + 1 checksum

    # Verify steps value (little endian)
    steps_bytes = cmd[1:3]
    assert int.from_bytes(steps_bytes, "little") == 10000
