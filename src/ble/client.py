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

        # Effective GATT UUIDs — start from known defaults, may be updated by
        # _find_huami_chars() on first connect when the device uses different UUIDs.
        self._notify_uuid: str = HUA_MI_DATA_NOTIFY_UUID
        self._write_uuid:  str = HUA_MI_DATA_CHAR_UUID
        self._auth_uuid:   str = HUA_MI_AUTH_CHAR_UUID

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

    async def _find_huami_chars(self) -> bool:
        """Discover and store the actual Huami GATT characteristic UUIDs.

        Strategy:
        1. Fast path: check that all three known UUIDs exist — use them as-is.
        2. Discovery path: scan service table for characteristics whose UUID
           contains the Huami proprietary suffix "3512-2118-0009af100700", then
           assign roles by BLE properties:
             - "notify"             → notify/response channel
             - "write" (lower UUID) → auth channel
             - "write" (higher UUID)→ command channel
        3. If mandatory characteristics are missing, set state.error with the
           full service/characteristic listing for diagnostics.

        Sets self._notify_uuid, self._write_uuid, self._auth_uuid and returns
        True when the mandatory notify + write pair is available.
        """
        if self._client is None:
            self._state.error = "Internal error: BleakClient is None in _find_huami_chars"
            return False

        _HUAMI_SUFFIX = "3512-2118-0009af100700"

        # Build uuid → properties map from all discovered services
        char_map: dict[str, list[str]] = {}
        for service in self._client.services:
            for char in service.characteristics:
                char_map[char.uuid.lower()] = list(char.properties)

        logger.debug(f"Device characteristics ({len(char_map)}): {list(char_map)}")

        # Fast path: standard Huami UUIDs present
        if (HUA_MI_DATA_NOTIFY_UUID.lower() in char_map
                and HUA_MI_DATA_CHAR_UUID.lower() in char_map
                and HUA_MI_AUTH_CHAR_UUID.lower() in char_map):
            logger.info("Standard Huami UUIDs confirmed on device")
            return True

        # Discovery path: find by UUID suffix
        huami = {u: p for u, p in char_map.items() if _HUAMI_SUFFIX in u}

        if not huami:
            all_chars = "\n".join(
                f"  {u}  props={sorted(p)}" for u, p in sorted(char_map.items())
            )
            self._state.error = (
                "未找到华米特征值（UUID 不含 3512-2118-0009af100700）。\n"
                "设备上全部特征值：\n" + all_chars
            )
            logger.error(self._state.error)
            return False

        # Assign roles by properties
        notify_chars = sorted(u for u, p in huami.items() if "notify" in p)
        write_chars  = sorted(u for u, p in huami.items()
                              if "write" in p or "write-without-response" in p)

        if not notify_chars or not write_chars:
            self._state.error = (
                f"华米特征值不完整（notify={notify_chars}, write={write_chars}）。\n"
                f"发现的华米特征值: {list(huami)}"
            )
            logger.error(self._state.error)
            return False

        notify_uuid = notify_chars[0]
        # Lower-numbered UUID = auth, higher = data write (matches 0x0009/0x0010)
        auth_uuid   = write_chars[0]
        data_uuid   = write_chars[1] if len(write_chars) >= 2 else write_chars[0]

        if notify_uuid != HUA_MI_DATA_NOTIFY_UUID.lower():
            logger.info(f"Non-standard notify UUID: {notify_uuid}")
        if data_uuid != HUA_MI_DATA_CHAR_UUID.lower():
            logger.info(f"Non-standard data-write UUID: {data_uuid}")
        if auth_uuid != HUA_MI_AUTH_CHAR_UUID.lower():
            logger.info(f"Non-standard auth UUID: {auth_uuid}")

        self._notify_uuid = notify_uuid
        self._write_uuid  = data_uuid
        self._auth_uuid   = auth_uuid
        return True

    async def connect(self) -> bool:
        """Establish BLE connection to the watch.

        On Windows, bleak's WinRT backend occasionally fails with
        "'NoneType' object has no attribute 'services'" when the internal
        device handle is stale (device was discovered but became briefly
        unavailable, or the Windows BLE stack has cached stale state).
        In that case we retry using the MAC address string, which forces
        bleak to perform a fresh device lookup via BleakScanner, bypassing
        the cached WinRT handle.
        """
        if self._ble_device is None:
            found = await self.scan()
            if found is None:
                self._state.error = "Device not found during scan"
                return False

        logger.info(f"Connecting to {self._ble_device.name or self.mac}...")

        # Try BLEDevice first (fast — uses cached WinRT device ID).
        # On Windows, fall back to MAC string (forces fresh device lookup)
        # if the first attempt fails with a WinRT stale-handle error.
        _targets: list = [self._ble_device]
        if sys.platform == "win32":
            _targets.append(self.mac)

        last_err = ""
        for attempt, conn_target in enumerate(_targets):
            self._client = BleakClient(conn_target, timeout=30.0)
            try:
                await self._client.connect()
                break  # connection succeeded
            except Exception as e:
                last_err = str(e)
                self._client = None
                if attempt < len(_targets) - 1 and (
                    "NoneType" in last_err or "services" in last_err.lower()
                    or "assert" in last_err.lower()
                ):
                    logger.warning(
                        f"Connect via BLEDevice failed ({e}), "
                        "retrying with MAC address string..."
                    )
                    continue
                self._state.error = (
                    f"Connection failed: {e}  "
                    "（请确保手表在附近且未被其他设备占用后重试）"
                )
                return False
        else:
            self._state.error = (
                f"Connection failed: {last_err}  "
                "（请重新扫描后再连接）"
            )
            return False

        # BLE link up — detect actual GATT UUIDs, then subscribe to notifications
        try:
            if not await self._find_huami_chars():
                try:
                    await self._client.disconnect()
                except Exception:
                    pass
                self._client = None
                return False

            await self._client.start_notify(
                self._notify_uuid,
                self._notification_handler,
            )
        except Exception as e:
            self._state.error = f"Connection failed: {e}"
            try:
                await self._client.disconnect()
            except Exception:
                pass
            self._client = None
            return False

        self._state.connected = True
        logger.info(
            f"BLE connected — notify={self._notify_uuid} "
            f"write={self._write_uuid} auth={self._auth_uuid}"
        )
        return True

    async def disconnect(self) -> None:
        """Disconnect from the watch."""
        if self._client and self._client.is_connected:
            try:
                await self._client.stop_notify(self._notify_uuid)
            except Exception:
                pass
            try:
                await self._client.disconnect()
            except Exception:
                pass

        self._state = ConnectionState()
        self._ble_device = None
        self._client = None
        # Reset to defaults so next connect re-discovers
        self._notify_uuid = HUA_MI_DATA_NOTIFY_UUID
        self._write_uuid  = HUA_MI_DATA_CHAR_UUID
        self._auth_uuid   = HUA_MI_AUTH_CHAR_UUID
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
                self._auth_uuid,
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
            self._auth_uuid,
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
                self._write_uuid,
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
                self._write_uuid,
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
    """Scan for nearby BLE devices, returning all with rich metadata.

    Uses return_adv=True (bleak 3.x) to get AdvertisementData per device,
    which provides real RSSI readings, manufacturer data (company ID), and
    advertised service UUIDs — enabling reliable Amazfit/Zepp identification
    even when the broadcast name is unusual or empty.

    Returns ALL discovered devices sorted: Amazfit/Zepp first, then by signal
    strength descending. Includes human-readable signal label and type hint.
    """
    _known_prefixes = ("amazfit", "t-rex", "gtr", "gts", "zepp", "bip", "band", "trex")

    # Huami Information Technology Co., Ltd. — Bluetooth SIG company ID 0x0157
    _HUAMI_COMPANY_ID = 0x0157

    # Service UUIDs that Huami/Amazfit devices advertise during discovery
    _HUAMI_SERVICE_UUIDS = {
        "0000fee0-0000-1000-8000-00805f9b34fb",  # Huami proprietary (main)
        "0000fee1-0000-1000-8000-00805f9b34fb",  # Huami proprietary (secondary)
    }

    logger.info("Scanning for BLE devices...")

    # return_adv=True → dict[addr, tuple[BLEDevice, AdvertisementData]]
    # AdvertisementData carries: rssi (int), manufacturer_data (dict[int,bytes]),
    # service_uuids (list[str]), local_name (str|None), tx_power (int|None)
    raw = await BleakScanner.discover(timeout=timeout, return_adv=True)

    results = []
    for addr, (device, adv) in raw.items():
        # local_name from advertisement is more reliable than cached BLEDevice.name
        name = adv.local_name or device.name or ""
        name_lower = name.lower()
        rssi = adv.rssi  # always int with return_adv=True

        # Three-source identification:
        # 1. Huami company ID in manufacturer data
        # 2. Known Huami service UUID in advertisement
        # 3. Device name prefix match
        has_huami_mfr = _HUAMI_COMPANY_ID in adv.manufacturer_data
        has_huami_svc = bool(
            {s.lower() for s in adv.service_uuids} & _HUAMI_SERVICE_UUIDS
        )
        if name_pattern:
            name_match = name_pattern.lower() in name_lower
        else:
            name_match = any(p in name_lower for p in _known_prefixes)

        is_amazfit = has_huami_mfr or has_huami_svc or name_match

        # Human-readable signal strength
        if rssi >= -60:
            signal = "极强"
        elif rssi >= -70:
            signal = "强"
        elif rssi >= -80:
            signal = "弱"
        else:
            signal = "极弱"

        results.append({
            "name":       name or addr,
            "mac":        addr,
            "rssi":       rssi,
            "signal":     signal,
            "is_amazfit": is_amazfit,
        })
        if is_amazfit:
            logger.info(f"  Amazfit device: {name or addr} ({addr}) RSSI={rssi} dBm")

    # Amazfit/Zepp devices first, then by RSSI descending within each group
    results.sort(key=lambda x: (0 if x["is_amazfit"] else 1, -x["rssi"]))
    logger.info(
        f"Scan complete: {len(results)} total, "
        f"{sum(1 for r in results if r['is_amazfit'])} Amazfit/Zepp"
    )
    return results
