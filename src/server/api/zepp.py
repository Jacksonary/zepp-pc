"""Zepp/Amazfit cloud login — fetch device list with auth keys.

Uses the current two-step Zepp API (as of 2024/2025):
  Step 1: POST encrypted credentials to api-user-us2.zepp.com → get access_token
  Step 2: POST access_token to api-mifit-us2.zepp.com/v2/client/login → get app_token
  Step 3: GET devices from api-mifit.zepp.com with app_token

Reference: https://github.com/argrento/huami-token (zepp.py + constants.py)
"""

import logging
import urllib.parse
import uuid

import httpx
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives import padding

logger = logging.getLogger(__name__)

# ── Zepp API endpoints (current as of 2025) ───────────────────────────
_URL_TOKENS   = "https://api-user-us2.zepp.com/v2/registrations/tokens"
_URL_LOGIN    = "https://api-mifit-us2.zepp.com/v2/client/login"
_URL_DEVICES  = "https://api-mifit.zepp.com/users/{user_id}/devices"

# AES-CBC encryption parameters for the token request payload
_ENC_KEY = b"xeNtBVqzDc6tuNTh"
_ENC_IV  = b"MAAAYAAAAAAAAABg"

_HEADERS_TOKENS = {
    "app_name": "com.huami.midong",
    "appname": "com.huami.midong",
    "User-Agent": "Zepp/9.12.5 (Pixel 4; Android 12; Density/2.75)",
    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
}

_HEADERS_LOGIN = {
    "app_name": "com.huami.midong",
    "appname": "com.huami.midong",
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:133.0) Gecko/20100101 Firefox/133.0",
    "origin": "https://user.zepp.com",
    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
}


def _encrypt_payload(data: bytes) -> bytes:
    """AES-128-CBC encrypt with PKCS7 padding (Zepp token request)."""
    padder = padding.PKCS7(128).padder()
    padded = padder.update(data) + padder.finalize()
    cipher = Cipher(algorithms.AES(_ENC_KEY), modes.CBC(_ENC_IV))
    encryptor = cipher.encryptor()
    return encryptor.update(padded) + encryptor.finalize()


async def get_devices_from_zepp(email: str, password: str, region: str = "international") -> list[dict]:
    """Login to Zepp cloud and return list of devices with auth keys.

    Args:
        email: Zepp account email
        password: Zepp account password
        region: "international" or "cn" (currently both use the same endpoint)
    """
    async with httpx.AsyncClient(timeout=15.0, follow_redirects=False) as client:

        # ── Step 1: Get access_token via encrypted credentials ────────
        token_payload = urllib.parse.urlencode({
            "emailOrPhone": email,
            "password": password,
            "state": "REDIRECTION",
            "client_id": "HuaMi",
            "redirect_uri": "https://s3-us-west-2.amazonaws.com/hm-registration/successsignin.html",
            "region": "us-west-2",
            "token": "access",
            "country_code": "US",
        }).encode()

        encrypted = _encrypt_payload(token_payload)

        resp1 = await client.post(
            _URL_TOKENS,
            content=encrypted,
            headers=_HEADERS_TOKENS,
        )

        # Server returns 303 redirect; access_token is in the Location query string
        if resp1.status_code == 303:
            location = resp1.headers.get("location", "")
            params = urllib.parse.parse_qs(urllib.parse.urlparse(location).query)
            access_token = (params.get("access") or [""])[0]
            if not access_token:
                raise ValueError(f"登录失败：重定向 URL 中未找到 access token（location={location!r}）")
        elif resp1.status_code == 200:
            # Some regions return 200 with JSON body
            data1 = resp1.json()
            access_token = data1.get("access_token") or data1.get("token_info", {}).get("access_token", "")
            if not access_token:
                msg = data1.get("message") or data1.get("error_message") or str(data1)
                raise ValueError(f"登录失败：{msg}")
        else:
            body = ""
            try:
                body = resp1.json()
            except Exception:
                body = resp1.text[:200]
            raise ValueError(f"登录失败（Step 1 HTTP {resp1.status_code}）：{body}")

        # ── Step 2: Exchange access_token for app_token ───────────────
        login_payload = {
            "code": access_token,
            "device_id": str(uuid.uuid4()),
            "device_model": "android_phone",
            "app_version": "9.12.5",
            "dn": "api-mifit.zepp.com,api-user.zepp.com,api-mifit.zepp.com,api-watch.zepp.com",
            "third_name": "huami",
            "source": "com.huami.watch.hmwatchmanager:9.12.5:151689",
            "app_name": "com.huami.midong",
            "country_code": "US",
            "grant_type": "access_token",
            "allow_registration": "false",
            "lang": "en",
            "countryState": "US-NY",
        }

        resp2 = await client.post(
            _URL_LOGIN,
            data=login_payload,
            headers=_HEADERS_LOGIN,
        )

        if resp2.status_code != 200:
            body = ""
            try:
                body = resp2.json()
            except Exception:
                body = resp2.text[:200]
            raise ValueError(f"登录失败（Step 2 HTTP {resp2.status_code}）：{body}")

        data2 = resp2.json()
        token_info = data2.get("token_info", {})
        app_token = token_info.get("app_token") or token_info.get("login_token")
        user_id = token_info.get("user_id")

        if not app_token:
            msg = data2.get("message") or data2.get("error_message") or str(data2)
            raise ValueError(f"登录失败：{msg}")

        # ── Step 3: Fetch device list ─────────────────────────────────
        resp3 = await client.get(
            _URL_DEVICES.format(user_id=user_id),
            headers={**_HEADERS_LOGIN, "apptoken": app_token},
        )
        resp3.raise_for_status()
        payload = resp3.json()

        devices_raw = payload.get("items") or (payload if isinstance(payload, list) else payload.get("devices", []))

        result = []
        for d in devices_raw:
            mac = d.get("macAddress") or d.get("mac_address") or d.get("deviceMacAddress")
            auth_key = d.get("hmac") or d.get("auth_key") or d.get("deviceKey")
            name = d.get("deviceName") or d.get("name") or "Unknown Device"
            if mac and auth_key:
                mac = mac.upper().replace("-", ":")
                auth_key = auth_key.replace(" ", "").lower()
                result.append({"mac": mac, "name": name, "auth_key": auth_key})

        return result
