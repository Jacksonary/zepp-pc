"""Device management API endpoints."""

import json
import logging
import os
import sys
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from src.ble.client import HuamiDevice, scan_for_amazfit_devices
from src.ble import commands as cmds


def get_static_dir() -> Path:
    """Get static files directory, works for both dev and PyInstaller."""
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS) / "src" / "server" / "static"
    return Path(__file__).parent.parent / "static"

logger = logging.getLogger(__name__)

router = APIRouter()

# In-memory device registry
# Key: MAC address, Value: HuamiDevice instance
_devices: dict[str, HuamiDevice] = {}

# Config file path for persisting auth keys
CONFIG_DIR = Path(os.path.expanduser("~/.zepp-pc"))
CONFIG_FILE = CONFIG_DIR / "devices.json"
CONFIG_DIR.mkdir(parents=True, exist_ok=True)


def _load_config() -> dict:
    """Load saved device config."""
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE) as f:
            return json.load(f)
    return {}


def _save_config(config: dict) -> None:
    """Save device config with atomic write (temp file + rename)."""
    tmp_path = CONFIG_FILE.with_suffix(".tmp")
    with open(tmp_path, "w") as f:
        json.dump(config, f, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp_path, CONFIG_FILE)


def _get_device(mac: str) -> HuamiDevice:
    """Get or create device instance."""
    if mac not in _devices:
        config = _load_config()
        auth_key = config.get(mac, {}).get("auth_key")
        _devices[mac] = HuamiDevice(mac=mac, auth_key=auth_key)
    return _devices[mac]


# ── Request Models ────────────────────────────────────────────────────

class AuthRequest(BaseModel):
    auth_key: str = ""


class ZeppLoginRequest(BaseModel):
    email: str
    password: str
    region: str = "international"


class DndRequest(BaseModel):
    enabled: bool = True
    start_h: int = 22
    start_m: int = 0
    end_h: int = 7
    end_m: int = 0


class GoalRequest(BaseModel):
    steps: int = 10000
    calories: int = 500
    active_min: int = 30


class NotificationRequest(BaseModel):
    message: str
    title: str = ""


@router.post("/zepp-login")
async def zepp_login(req: ZeppLoginRequest):
    """Login to Zepp cloud, import all bound devices with their auth keys."""
    from src.server.api.zepp import get_devices_from_zepp
    try:
        cloud_devices = await get_devices_from_zepp(req.email, req.password, req.region)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        logger.error(f"Zepp login error: {e}")
        raise HTTPException(500, f"网络错误：{e}")

    if not cloud_devices:
        raise HTTPException(404, "该账号下未找到已绑定的手表设备")

    config = _load_config()
    added = []
    for d in cloud_devices:
        mac = d["mac"]
        config.setdefault(mac, {})["auth_key"] = d["auth_key"]
        config[mac]["name"] = d["name"]
        if mac not in _devices:
            _devices[mac] = HuamiDevice(mac=mac, auth_key=d["auth_key"])
        else:
            _devices[mac].auth_key = d["auth_key"]
        added.append({"mac": mac, "name": d["name"]})

    _save_config(config)
    return {"devices": added, "count": len(added)}


# ── UI ────────────────────────────────────────────────────────────────

@router.get("/")
async def index():
    """Serve the main UI."""
    index_path = get_static_dir() / "index.html"
    return HTMLResponse(content=index_path.read_text())


# ── Device Discovery ──────────────────────────────────────────────────

@router.get("/scan")
async def scan_devices():
    """Scan for nearby Amazfit/Zepp BLE devices."""
    try:
        results = await scan_for_amazfit_devices(timeout=8.0)
        return {"devices": results}
    except Exception as e:
        raise HTTPException(500, f"蓝牙扫描失败：{e}")


# ── Device Management ─────────────────────────────────────────────────

@router.get("/devices")
async def list_devices():
    """List all configured/connected devices."""
    config = _load_config()
    result = []
    for mac, device in _devices.items():
        state = device.state
        result.append({
            "mac": mac,
            "name": state.device_info.name if state.device_info else mac,
            "connected": state.connected,
            "authenticated": state.authenticated,
            "battery": state.device_info.battery_level if state.device_info else None,
            "model": state.device_info.model if state.device_info else "",
            "firmware": state.device_info.firmware_version if state.device_info else "",
            "error": state.error,
            "saved_key": mac in config,
        })
    return result


@router.post("/devices/{mac}")
async def add_device(mac: str):
    """Add a device by MAC address."""
    device = _get_device(mac)
    # Don't overwrite existing state
    return {"mac": mac, "added": True}


@router.get("/devices/{mac}")
async def get_device(mac: str):
    """Get device details."""
    device = _get_device(mac)
    state = device.state
    return {
        "mac": mac,
        "name": state.device_info.name if state.device_info else mac,
        "connected": state.connected,
        "authenticated": state.authenticated,
        "device_info": {
            "model": state.device_info.model if state.device_info else "",
            "firmware": state.device_info.firmware_version if state.device_info else "",
            "serial": state.device_info.serial_number if state.device_info else "",
            "hardware": state.device_info.hardware_version if state.device_info else "",
            "battery": state.device_info.battery_level if state.device_info else None,
        },
        "error": state.error,
    }


@router.post("/devices/{mac}/auth")
async def authenticate(mac: str, req: AuthRequest):
    """Authenticate with the device using an auth key."""
    device = _get_device(mac)

    # Update device auth key (only if a new key was provided in the request)
    if req.auth_key:
        config = _load_config()
        config.setdefault(mac, {})["auth_key"] = req.auth_key
        _save_config(config)
        device.auth_key = req.auth_key

    if not device.auth_key:
        raise HTTPException(400, "Auth key not set — provide auth_key in request body")

    # Connect and authenticate
    if not device.state.connected:
        success = await device.connect()
        if not success:
            raise HTTPException(400, device.state.error or "Connection failed")

    success = await device.authenticate()
    if not success:
        raise HTTPException(401, device.state.error or "Authentication failed")

    # Read device info after successful auth
    try:
        await device.read_device_info()
        await device.read_battery()
    except Exception as e:
        logger.warning(f"Failed to read device info: {e}")

    return {
        "authenticated": True,
        "device_info": {
            "name": device.state.device_info.name if device.state.device_info else "",
            "model": device.state.device_info.model if device.state.device_info else "",
            "firmware": device.state.device_info.firmware_version if device.state.device_info else "",
            "battery": device.state.device_info.battery_level if device.state.device_info else None,
        },
    }


@router.post("/devices/{mac}/connect")
async def connect_device(mac: str):
    """Connect to a device (without auth)."""
    device = _get_device(mac)
    success = await device.connect()
    if not success:
        raise HTTPException(400, device.state.error or "Connection failed")
    return {"connected": True}


@router.post("/devices/{mac}/disconnect")
async def disconnect_device(mac: str):
    """Disconnect from a device."""
    device = _get_device(mac)
    await device.disconnect()
    return {"disconnected": True}


@router.delete("/devices/{mac}")
async def remove_device(mac: str):
    """Remove a device from config."""
    device = _get_device(mac)
    await device.disconnect()
    config = _load_config()
    config.pop(mac, None)
    _save_config(config)
    _devices.pop(mac, None)
    return {"removed": True}


# ── Data Reading ──────────────────────────────────────────────────────

@router.get("/devices/{mac}/battery")
async def get_battery(mac: str):
    """Read battery level."""
    device = _get_device(mac)
    if not device.state.connected:
        raise HTTPException(400, "Not connected")
    level = await device.read_battery()
    return {"battery": level}


@router.get("/devices/{mac}/steps")
async def get_steps(mac: str):
    """Read step count."""
    device = _get_device(mac)
    if not device.state.connected:
        raise HTTPException(400, "Not connected")
    resp = await device.send_command(cmds.get_steps_cmd())
    if resp is None:
        raise HTTPException(500, "No response from device")
    return {"steps": cmds.parse_steps_response(resp)}


@router.get("/devices/{mac}/heart_rate")
async def get_heart_rate(mac: str):
    """Read real-time heart rate."""
    device = _get_device(mac)
    if not device.state.connected:
        raise HTTPException(400, "Not connected")
    resp = await device.send_command(cmds.get_heart_rate_cmd())
    if resp is None:
        raise HTTPException(500, "No response from device")
    return {"heart_rate": cmds.parse_heart_rate_response(resp)}


@router.get("/devices/{mac}/spo2")
async def get_spo2(mac: str):
    """Read SpO2 level."""
    device = _get_device(mac)
    if not device.state.connected:
        raise HTTPException(400, "Not connected")
    resp = await device.send_command(cmds.get_spo2_cmd())
    if resp is None:
        raise HTTPException(500, "No response from device")
    return {"spo2": cmds.parse_spo2_response(resp)}


@router.get("/devices/{mac}/info")
async def get_device_info(mac: str):
    """Read device info (model, firmware, etc.)."""
    device = _get_device(mac)
    if not device.state.connected:
        raise HTTPException(400, "Not connected")
    info = await device.read_device_info()
    return {
        "name": info.name,
        "mac": info.mac,
        "model": info.model,
        "firmware": info.firmware_version,
        "serial": info.serial_number,
        "hardware": info.hardware_version,
    }


# ── Sync (all data at once) ──────────────────────────────────────────

@router.get("/devices/{mac}/sync")
async def sync_device(mac: str):
    """Sync all available data from device."""
    device = _get_device(mac)
    if not device.state.connected:
        raise HTTPException(400, "Not connected")

    results = {}

    # Battery
    try:
        results["battery"] = await device.read_battery()
    except Exception as e:
        results["battery"] = None
        logger.warning(f"Battery read failed: {e}")

    # Steps
    try:
        resp = await device.send_command(cmds.get_steps_cmd())
        results["steps"] = cmds.parse_steps_response(resp) if resp else None
    except Exception as e:
        results["steps"] = None
        logger.warning(f"Steps read failed: {e}")

    # Heart rate
    try:
        resp = await device.send_command(cmds.get_heart_rate_cmd())
        results["heart_rate"] = cmds.parse_heart_rate_response(resp) if resp else None
    except Exception as e:
        results["heart_rate"] = None
        logger.warning(f"Heart rate read failed: {e}")

    # SpO2
    try:
        resp = await device.send_command(cmds.get_spo2_cmd())
        results["spo2"] = cmds.parse_spo2_response(resp) if resp else None
    except Exception as e:
        results["spo2"] = None
        logger.warning(f"SpO2 read failed: {e}")

    # Device info
    try:
        info = await device.read_device_info()
        results["device_info"] = {
            "model": info.model,
            "firmware": info.firmware_version,
            "serial": info.serial_number,
            "hardware": info.hardware_version,
        }
    except Exception as e:
        results["device_info"] = None
        logger.warning(f"Device info read failed: {e}")

    return results


# ── Actions ───────────────────────────────────────────────────────────

@router.post("/devices/{mac}/find")
async def find_device(mac: str):
    """Trigger find device (watch vibrates for 3 seconds)."""
    device = _get_device(mac)
    if not device.state.connected:
        raise HTTPException(400, "Not connected")
    await device.send_command(cmds.find_device_cmd(), expect_response=False)
    return {"finding": True}


@router.post("/devices/{mac}/sync_time")
async def sync_time(mac: str):
    """Sync PC time to the watch."""
    device = _get_device(mac)
    if not device.state.connected:
        raise HTTPException(400, "Not connected")
    await device.send_command(cmds.set_time_cmd())
    return {"synced": True}


@router.post("/devices/{mac}/notification")
async def send_notification(mac: str, req: NotificationRequest):
    """Push a notification to the watch."""
    device = _get_device(mac)
    if not device.state.connected:
        raise HTTPException(400, "Not connected")
    await device.send_notification_command(req.message, req.title)
    return {"sent": True}


@router.post("/devices/{mac}/dnd")
async def set_dnd(mac: str, req: DndRequest):
    """Set Do Not Disturb schedule."""
    device = _get_device(mac)
    if not device.state.connected:
        raise HTTPException(400, "Not connected")
    await device.send_command(
        cmds.set_dnd_cmd(req.start_h, req.start_m, req.end_h, req.end_m, req.enabled)
    )
    return {"configured": True}


@router.post("/devices/{mac}/goal")
async def set_goal(mac: str, req: GoalRequest):
    """Set daily activity goals."""
    device = _get_device(mac)
    if not device.state.connected:
        raise HTTPException(400, "Not connected")
    await device.send_command(cmds.set_goal_cmd(req.steps, req.calories, req.active_min))
    return {"configured": True}
