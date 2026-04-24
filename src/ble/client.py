"""
BLE client wrapper for Amazfit/Zepp smartwatches using bleak.

Handles:
- Device scanning (by MAC or by Huami service advertisement)
- BLE connection / disconnection
- Authentication (AES-128 challenge-response)
- Command send/receive with GATT characteristics
- Health data reading (battery, steps, SpO2)

Note on Zepp OS 2.x (T-Rex 3):
    Zepp OS devices use the same Huami protocol family but with
    potentially different GATT characteristic UUIDs. The UUIDs below
    are the standard set used across Bip/T-Rex/GTR series.
    If connection fails, the watch may use Zepp OS-specific UUIDs —
    check Gadgetbridge's device coordinator for exact values.
"""

import asyncio
import logging
import secrets
import sys

from bleak import BleakClient, BleakScanner, BLEDevice

from src.ble.auth import compute_auth_response, parse_auth_key
from src.models.device import ConnectionState, DeviceInfo

logger = logging.getLogger(__name__)

# ── Huami BLE GATT UUIDs ──────────────────────────────────────────────
# These are the standard Huami/Amazfit BLE characteristic UUIDs used
# across most Amazfit devices (Bip, T-Rex, GTR, GTS series).
# Zepp OS 2.x devices (T-Rex 3) may use the same or slightly different
# UUIDs. If authentication fails, verify against Gadgetbridge's
# device coordinator implementation.

# Huami proprietary service
HUA_MI_AUTH_CHAR_UUID = "00000009-0000-3512-2118-0009af100700"
HUA_MI_DATA_CHAR_UUID = "00000010-0000-3512-2118-0009af100700"
HUA_MI_DATA_NOTIFY_UUID = "00000011-0000-3512-2118-0009af100700"

# Standard BLE characteristics (Device Information service)
MODEL_NUMBER_CHAR = "00002a24-0000-1000-8000-00805f9b34fb"
FIRMWARE_REV_CHAR = "00002a26-0000-1000-8000-00805f9b34fb"
SERIAL_NUMBER_CHAR = "00002a25-0000-1000-8000-00805f9b34fb"
HARDWARE_REV_CHAR = "00002a27-0000-1000-8000-00805f9b34fb"

BATTERY_LEVEL_CHAR = "00002a19-0000-1000-8000-00805f9b34fb"


class HuamiDevice:
    """High-level interface to a connected Amazfit/Zepp watch."""

    def __init__(self, mac: str, auth_key: str | None = None):
        self.mac = mac
        self._ble_device: BLEDevice | None = None
        self._client: BleakClient | None = None
        self._state = ConnectionState()
        self._auth_key = auth_key
        self._data_buffer = bytearray()
        self._response_event = asyncio.Event()
        self._command_lock = asyncio.Lock()
        self._expecting_response = False

    @property
    def state(self) -> ConnectionState:
        return self._state

    @property
    def auth_key(self) -> str | None:
        return self._auth_key

    @auth_key.setter
    def auth_key(self, value: str) -> None:
        self._auth_key = value

    async def scan(self, timeout: float = 5.0) -> BLEDevice | None:
        """Scan for BLE devices and find the one matching our MAC."""
        logger.info(f"Scanning for device {self.mac}...")
        try:
            devices = await BleakScanner.discover(timeout=timeout)
        except Exception as e:
            self._state.error = f"BLE scan failed: {e}"
            return None
        for d in devices:
            d_addr = d.address.replace(":", "").replace("-", "").upper()
            target = self.mac.replace(":", "").replace("-", "").upper()
            if d_addr == target:
                self._ble_device = d
                logger.info(f"Found device: {d.name or d.address}")
                return d

        logger.warning(f"Device {self.mac} not found")
        return None

    async def connect(self) -> bool:
        """Establish BLE connection to the watch."""
        if self._ble_device is None:
            found = await self.scan()
            if found is None:
                self._state.error = "Device not found during scan"
                return False

        logger.info(f"Connecting to {self._ble_device.name or self.mac}...")

        self._client = BleakClient(
            self._ble_device,
            timeout=30.0,
        )

        try:
            await self._client.connect()

            # Set up data notification listener — required for all command responses
            # and auth flow (watch sends responses via HUA_MI_DATA_NOTIFY_UUID)
            await self._client.start_notify(
                HUA_MI_DATA_NOTIFY_UUID,
                self._notification_handler,
            )
        except Exception as e:
            self._state.error = f"Connection failed: {e}"
            self._client = None
            return False

        self._state.connected = True
        logger.info("BLE connected and notification enabled")

        return True

    async def disconnect(self) -> None:
        """Disconnect from the watch."""
        if self._client and self._client.is_connected:
            try:
                await self._client.stop_notify(HUA_MI_DATA_NOTIFY_UUID)
            except Exception:
                pass
            try:
                await self._client.disconnect()
            except Exception:
                pass

        self._state = ConnectionState()
        self._ble_device = None
        self._client = None
        logger.info("Disconnected")

    async def authenticate(self) -> bool:
        """Perform AES-128 authentication with the watch.

        Huami protocol flow:
        1. Send our 16-byte nonce to watch (cmd 0x01)
        2. Watch responds with its nonce + our nonce encrypted with auth key
        3. We verify the encrypted nonce
        4. Send back watch's nonce encrypted with our auth key
        5. Watch confirms — authenticated

        Requires auth_key to be set (from huami-token).
        """
        if self._auth_key is None:
            self._state.error = "Auth key not set"
            return False

        if not self._client or not self._client.is_connected:
            self._state.error = "Not connected"
            return False

        try:
            key_bytes = parse_auth_key(self._auth_key)
        except ValueError as e:
            self._state.error = str(e)
            return False

        # Step 1: Send our nonce
        our_nonce = secrets.token_bytes(16)
        logger.info(f"Sending auth challenge (nonce={our_nonce[:4].hex()}...)")

        # Auth packet format: [cmd=0x01, nonce(16)]
        auth_packet = bytes([0x01]) + our_nonce

        # Enable response capture for auth flow
        self._data_buffer.clear()
        self._response_event.clear()
        self._expecting_response = True

        try:
            await self._client.write_gatt_char(
                HUA_MI_AUTH_CHAR_UUID,
                auth_packet,
                response=True,
            )
        except Exception as e:
            self._expecting_response = False
            self._state.error = f"Auth send failed: {e}"
            return False

        # Step 2: Wait for watch response
        try:
            await asyncio.wait_for(self._response_event.wait(), timeout=10.0)
        except asyncio.TimeoutError:
            self._expecting_response = False
            self._state.error = "Authentication timeout — watch did not respond"
            return False

        response = bytes(self._data_buffer)
        self._data_buffer.clear()
        self._expecting_response = False
        logger.info(f"Auth response received: {response.hex()}")

        # Step 3: Parse and verify response
        # Format: [cmd=0x02, status(1), watch_nonce(16), encrypted_our_nonce(16)]
        if len(response) < 34:
            self._state.error = f"Invalid auth response length: {len(response)}"
            return False

        watch_nonce = response[2:18]
        encrypted_our_nonce = response[18:34]

        expected = compute_auth_response(key_bytes, our_nonce)
        if encrypted_our_nonce != expected:
            self._state.error = "Auth key mismatch — wrong key for this device"
            logger.warning(
                f"Auth key mismatch: expected {expected.hex()}, got {encrypted_our_nonce.hex()}"
            )
            return False

        # Step 4: Send our encrypted version of watch's nonce
        logger.info(f"Auth challenge verified, sending confirmation...")
        our_response = compute_auth_response(key_bytes, watch_nonce)
        confirm_packet = bytes([0x02]) + our_response

        # Step 5: Wait for confirmation
        self._data_buffer.clear()
        self._response_event.clear()
        self._expecting_response = True

        await self._client.write_gatt_char(
            HUA_MI_AUTH_CHAR_UUID,
            confirm_packet,
            response=True,
        )

        try:
            await asyncio.wait_for(self._response_event.wait(), timeout=5.0)
        except asyncio.TimeoutError:
            # Some devices don't send a confirmation packet
            self._expecting_response = False
            logger.warning("No auth confirmation received, assuming authenticated")
            self._state.authenticated = True
            return True

        confirm = bytes(self._data_buffer)
        self._data_buffer.clear()
        self._expecting_response = False

        # Confirmation: [cmd=0x03, result(1)] where result=0x01 means success
        if len(confirm) >= 2 and confirm[1] == 0x01:
            self._state.authenticated = True
            logger.info("Authentication successful")
            return True
        else:
            self._state.error = "Authentication rejected by device"
            return False

    def _notification_handler(self, sender, data: bytearray) -> None:
        """Handle incoming BLE notifications.

        Only signals the response event when a command is actively waiting.
        This prevents unsolicited notifications (e.g. heart rate pushes)
        from prematurely unblocking send_command.
        """
        logger.debug(f"BLE notification [{sender}]: {data.hex()}")
        if self._expecting_response:
            self._data_buffer.extend(data)
            self._response_event.set()

    async def send_command(self, cmd: bytes, expect_response: bool = True) -> bytes | None:
        """Send a command via data characteristic.

        Uses an asyncio.Lock to serialize command/response pairs,
        and an _expecting_response flag to ignore unsolicited notifications.
        """
        if not self._client or not self._client.is_connected:
            raise RuntimeError("Not connected")

        async with self._command_lock:
            self._data_buffer.clear()
            self._response_event.clear()
            self._expecting_response = expect_response

            await self._client.write_gatt_char(
                HUA_MI_DATA_CHAR_UUID,
                cmd,
                response=True,
            )

            if expect_response:
                try:
                    await asyncio.wait_for(self._response_event.wait(), timeout=10.0)
                    return bytes(self._data_buffer)
                except asyncio.TimeoutError:
                    return None
                finally:
                    self._expecting_response = False
        return None

    async def send_notification_command(self, message: str, title: str = "") -> bool:
        """Push a notification to the watch.

        Huami notification packet:
          [0x01, 0x01, len_lo, len_hi, title_utf8, 0x00, message_utf8, checksum]
        The null byte between title and message is required so the watch can
        split them into separate display fields.
        """
        if not self._client or not self._client.is_connected:
            raise RuntimeError("Not connected")

        title_bytes = title.encode("utf-8") if title else b""
        msg_bytes   = message.encode("utf-8")

        # Separator is only added when there is a title
        body = (title_bytes + b"\x00" + msg_bytes) if title_bytes else msg_bytes
        raw_payload = bytes([0x01, 0x01]) + len(body).to_bytes(2, "little") + body
        checksum = sum(raw_payload) & 0xFF
        payload = raw_payload + bytes([checksum])

        async with self._command_lock:
            self._data_buffer.clear()
            self._response_event.clear()
            await self._client.write_gatt_char(
                HUA_MI_DATA_CHAR_UUID,
                payload,
                response=True,
            )
        return True

    async def read_device_info(self) -> DeviceInfo:
        """Read device info from standard BLE characteristics."""
        if not self._client:
            raise RuntimeError("Not connected")

        async def read_char(uuid: str) -> str:
            try:
                data = await self._client.read_gatt_char(uuid)
                return data.decode("utf-8", errors="replace").strip()
            except Exception:
                return ""

        model = await read_char(MODEL_NUMBER_CHAR)
        firmware = await read_char(FIRMWARE_REV_CHAR)
        serial = await read_char(SERIAL_NUMBER_CHAR)
        hardware = await read_char(HARDWARE_REV_CHAR)
        name = self._ble_device.name if self._ble_device else self.mac

        info = DeviceInfo(
            name=name or "Unknown",
            mac=self.mac,
            model=model,
            firmware_version=firmware,
            serial_number=serial,
            hardware_version=hardware,
        )

        self._state.device_info = info
        return info

    async def read_battery(self) -> int:
        """Read battery level from standard battery service."""
        if not self._client:
            raise RuntimeError("Not connected")

        try:
            data = await self._client.read_gatt_char(BATTERY_LEVEL_CHAR)
            level = data[0] if data else 0
            if self._state.device_info:
                self._state.device_info.battery_level = level
            return level
        except Exception as e:
            logger.warning(f"Failed to read battery: {e}")
            return 0


async def scan_for_amazfit_devices(name_pattern: str = "", timeout: float = 8.0) -> list[dict]:
    """Scan for nearby BLE devices.

    Returns ALL discovered devices sorted so known Amazfit/Zepp models come first.
    This lets the user select their watch even if the BLE broadcast name is unexpected.

    On Windows, Python 3.12 uvicorn already runs on ProactorEventLoop which bleak's
    WinRT backend requires. Run directly in the current event loop — do NOT use
    run_in_executor with a new loop, because WinRT BLEDevice objects are COM-apartment-
    threaded and must be used on the loop that created them.
    """
    _known_prefixes = ("amazfit", "t-rex", "gtr", "gts", "zepp", "bip", "band", "trex")
    logger.info("Scanning for BLE devices...")

    raw_devices = await BleakScanner.discover(timeout=timeout)

    results = []
    for d in raw_devices:
        name = d.name or ""
        name_lower = name.lower()

        if name_pattern:
            is_match = name_pattern.lower() in name_lower
        else:
            is_match = any(p in name_lower for p in _known_prefixes)

        # Collect RSSI — bleak 0.22+ moved it to AdvertisementData,
        # but BLEDevice.rssi still exists as a convenience property in most versions.
        rssi = getattr(d, "rssi", None)

        results.append({
            "name":       name or d.address,
            "mac":        d.address,
            "rssi":       rssi,
            "is_amazfit": is_match,
        })
        if is_match:
            logger.info(f"  Amazfit device: {name} ({d.address})")

    # Sort: known Amazfit devices first, then by RSSI descending (signal strength)
    results.sort(key=lambda x: (0 if x["is_amazfit"] else 1, -(x["rssi"] or -100)))
    logger.info(f"Scan complete: {len(results)} total, "
                f"{sum(1 for r in results if r['is_amazfit'])} Amazfit/Zepp")
    return results
