"""Zepp/Amazfit cloud login — fetch device list with auth keys.

Uses the current two-step Zepp API (as of 2024/2025):
  Step 1: POST AES-CBC-encrypted credentials → get access_token (303 redirect)
  Step 2: POST access_token → get app_token + user_id
  Step 3: GET devices with app_token + required query params

Reference: https://github.com/argrento/huami-token (zepp.py + constants.py + models.py)
"""

import json
import logging
import secrets
import urllib.parse
import uuid

import httpx
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives import padding

logger = logging.getLogger(__name__)

# ── Zepp API endpoints ────────────────────────────────────────────────
_URL_TOKENS_INTL = "https://api-user-us2.zepp.com/v2/registrations/tokens"
_URL_TOKENS_CN   = "https://api-user-cn2.zepp.com/v2/registrations/tokens"
_URL_LOGIN_INTL  = "https://api-mifit-us2.zepp.com/v2/client/login"
_URL_LOGIN_CN    = "https://api-mifit-cn2.zepp.com/v2/client/login"
_URL_DEVICES     = "https://api-mifit.zepp.com/users/{user_id}/devices"

# AES-128-CBC encryption — key + IV from huami-token constants.py
_ENC_KEY = b"xeNtBVqzDc6tuNTh"
_ENC_IV  = b"MAAAYAAAAAAAAABg"

# Step 1: All 11 required headers (missing any → 400 Bad Request from server)
_HEADERS_TOKENS = {
    "app_name":        "com.huami.midong",
    "appname":         "com.huami.midong",
    "cv":              "151689_9.12.5",
    "v":               "2.0",
    "appplatform":     "android_phone",
    "vb":              "202509151347",
    "vn":              "9.12.5",
    "User-Agent":      "Zepp/9.12.5 (Pixel 4; Android 12; Density/2.75)",
    "x-hm-ekv":       "1",
    "Content-Type":    "application/x-www-form-urlencoded; charset=UTF-8",
    "Accept-Encoding": "gzip",
}

# Step 2: Login headers
_HEADERS_LOGIN = {
    "app_name":     "com.huami.midong",
    "appname":      "com.huami.midong",
    "User-Agent":   "Mozilla/5.0 (X11; Linux x86_64; rv:133.0) Gecko/20100101 Firefox/133.0",
    "origin":       "https://user.zepp.com",
    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
}

# Step 3: Device list headers (all required by the server)
_HEADERS_DEVICES = {
    "hm-privacy-diagnostics": "false",
    "hm-privacy-ceip":        "true",
    "country":                "US",
    "appplatform":            "android_phone",
    "timezone":               "Europe/London",
    "channel":                "a100900101016",
    "vb":                     "202509151347",
    "cv":                     "151689_9.12.5",
    "appname":                "com.huami.midong",
    "v":                      "2.0",
    "vn":                     "9.12.5",
    "lang":                   "en_US",
    "User-Agent":             "Zepp/9.12.5 (Pixel 4; Android 12; Density/2.75)",
    "Accept-Encoding":        "gzip",
}


def _encrypt_payload(data: bytes) -> bytes:
    """AES-128-CBC encrypt with PKCS7 padding."""
    padder = padding.PKCS7(128).padder()
    padded = padder.update(data) + padder.finalize()
    cipher = Cipher(algorithms.AES(_ENC_KEY), modes.CBC(_ENC_IV))
    encryptor = cipher.encryptor()
    return encryptor.update(padded) + encryptor.finalize()


def _parse_auth_key(d: dict) -> str:
    """Extract auth_key from a device dict.

    The Zepp API buries the auth_key inside an 'additionalInfo' field that is
    itself a JSON-encoded string:
      {"additionalInfo": "{\"auth_key\": \"aabbccdd...\", ...}", ...}

    Fall back to top-level field names used by older API versions.
    """
    # Primary: nested JSON string in additionalInfo (current API)
    additional_info_str = d.get("additionalInfo") or d.get("additional_info")
    if additional_info_str:
        try:
            additional_info = json.loads(additional_info_str)
            key = additional_info.get("auth_key") or additional_info.get("hmac")
            if key:
                return key
        except (json.JSONDecodeError, TypeError):
            pass

    # Fallbacks: top-level fields used by older / alternate API versions
    return (
        d.get("hmac")
        or d.get("auth_key")
        or d.get("deviceKey")
        or d.get("authKey")
        or ""
    )


async def get_devices_from_zepp(email: str, password: str, region: str = "international") -> list[dict]:
    """Login to Zepp cloud and return list of devices with auth keys."""
    is_cn = region == "cn"
    url_tokens = _URL_TOKENS_CN if is_cn else _URL_TOKENS_INTL
    url_login  = _URL_LOGIN_CN  if is_cn else _URL_LOGIN_INTL

    async with httpx.AsyncClient(timeout=15.0, follow_redirects=False) as client:

        # ── Step 1: Encrypted credential exchange → access_token ──────
        # token must be a list: urlencode(doseq=True) emits token=access&token=refresh
        raw_payload = urllib.parse.urlencode({
            "emailOrPhone": email,
            "password":     password,
            "state":        "REDIRECTION",
            "client_id":    "HuaMi",
            "redirect_uri": "https://s3-us-west-2.amazonaws.com/hm-registration/successsignin.html",
            "region":       "us-west-2",
            "token":        ["access", "refresh"],
            "country_code": "US",
        }, doseq=True).encode()

        resp1 = await client.post(
            url_tokens,
            content=_encrypt_payload(raw_payload),
            headers=_HEADERS_TOKENS,
        )

        if resp1.status_code == 303:
            location = resp1.headers.get("location", "")
            params = urllib.parse.parse_qs(urllib.parse.urlparse(location).query)
            access_token = (params.get("access") or [""])[0]
            if not access_token:
                raise ValueError(
                    f"登录失败：重定向 URL 中未找到 access token（Location: {location!r}）"
                )
        elif resp1.status_code == 200:
            data1 = resp1.json()
            access_token = (
                data1.get("access_token")
                or data1.get("token_info", {}).get("access_token", "")
            )
            if not access_token:
                msg = data1.get("message") or data1.get("error_message") or str(data1)
                raise ValueError(f"登录失败：{msg}")
        else:
            try:
                body = resp1.json()
            except Exception:
                body = resp1.text[:300]
            raise ValueError(f"登录失败（Step 1 HTTP {resp1.status_code}）：{body}")

        # ── Step 2: access_token → app_token + user_id ────────────────
        resp2 = await client.post(
            url_login,
            data={
                "code":               access_token,
                "device_id":          str(uuid.uuid4()),
                "device_model":       "android_phone",
                "app_version":        "9.12.5",
                "dn":                 "api-mifit.zepp.com,api-user.zepp.com,api-watch.zepp.com",
                "third_name":         "huami",
                "source":             "com.huami.watch.hmwatchmanager:9.12.5:151689",
                "app_name":           "com.huami.midong",
                "country_code":       "US",
                "grant_type":         "access_token",
                "allow_registration": "false",
                "lang":               "en",
                "countryState":       "US-NY",
            },
            headers=_HEADERS_LOGIN,
        )

        if resp2.status_code != 200:
            try:
                body = resp2.json()
            except Exception:
                body = resp2.text[:300]
            raise ValueError(f"登录失败（Step 2 HTTP {resp2.status_code}）：{body}")

        data2 = resp2.json()
        token_info = data2.get("token_info", {})
        app_token = token_info.get("app_token") or token_info.get("login_token")
        user_id   = token_info.get("user_id")

        if not app_token or not user_id:
            msg = data2.get("message") or data2.get("error_message") or str(data2)
            raise ValueError(f"登录失败：{msg}")

        # ── Step 3: Fetch device list ─────────────────────────────────
        # Required query params (from huami-token URL_PARAMS.ZEPP_DEVICES):
        # r, userid, appid are dynamic; the rest are fixed config values.
        req_id = str(uuid.uuid4())
        params3 = {
            "r":                        [req_id, req_id],
            "enableMultiDeviceOnMultiType": ["true", "true"],
            "userid":                   user_id,
            "appid":                    str(secrets.randbits(64)),
            "channel":                  "a100900101016",
            "country":                  "US",
            "cv":                       "151689_9.12.5",
            "device":                   "android_32",
            "device_type":              "android_phone",
            "enableMultiDevice":        "true",
            "lang":                     "en_US",
            "timezone":                 "Europe/London",
            "v":                        "2.0",
        }

        resp3 = await client.get(
            _URL_DEVICES.format(user_id=user_id),
            params=params3,
            headers={
                **_HEADERS_DEVICES,
                "x-request-id": req_id,
                "apptoken":     app_token,
            },
        )

        if resp3.status_code != 200:
            try:
                body = resp3.json()
            except Exception:
                body = resp3.text[:300]
            raise ValueError(f"获取设备列表失败（HTTP {resp3.status_code}）：{body}")

        payload = resp3.json()
        logger.info(f"Device list response keys: {list(payload.keys()) if isinstance(payload, dict) else 'list'}")

        # "items" is the canonical key; use explicit presence check so an empty
        # list [] (no devices bound) is handled correctly and not shadowed by `or`.
        if "items" in payload:
            devices_raw = payload["items"]
        elif isinstance(payload, list):
            devices_raw = payload
        else:
            devices_raw = payload.get("devices", [])

        logger.info(f"Raw device count: {len(devices_raw)}")

        result = []
        for d in devices_raw:
            mac      = d.get("macAddress") or d.get("mac_address") or d.get("deviceMacAddress")
            auth_key = _parse_auth_key(d)
            name     = d.get("deviceName") or d.get("name") or "Unknown Device"

            if not mac:
                logger.warning(f"Device missing MAC, skipping: {list(d.keys())}")
                continue
            if not auth_key:
                logger.warning(f"Device {mac} missing auth_key, fields: {list(d.keys())}")
                continue

            mac      = mac.upper().replace("-", ":")
            auth_key = auth_key.replace(" ", "").lower()
            result.append({"mac": mac, "name": name, "auth_key": auth_key})
            logger.info(f"Device imported: {name} ({mac})")

        return result
