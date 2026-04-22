"""Zepp/Amazfit cloud login — fetch device list with auth keys."""

import logging

import httpx

logger = logging.getLogger(__name__)

# International accounts (amazfit.com / zepp.com)
_LOGIN_URL = "https://account.huami.com/v2/client/login"
# China accounts (zepp.com China region)
_LOGIN_URL_CN = "https://account-cn.huami.com/v2/client/login"
_DEVICE_URL = "https://app-device.huami.com/device/amazfit_v2/users/self/devices"

_HEADERS = {
    "User-Agent": "MiFit/4.6.0 (Android)",
    "Content-Type": "application/x-www-form-urlencoded",
}


async def get_devices_from_zepp(email: str, password: str, region: str = "international") -> list[dict]:
    """Login to Zepp/Amazfit cloud and return list of devices with auth keys.

    Args:
        email: Zepp account email
        password: Zepp account password (plain text, sent over HTTPS)
        region: "international" for amazfit.com accounts, "cn" for zepp.com China accounts
    """
    login_url = _LOGIN_URL_CN if region == "cn" else _LOGIN_URL

    async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
        # Step 1: Login to get access token
        resp = await client.post(
            login_url,
            data={
                "client_id": "HuaMi",
                "password": password,
                "redirect_uri": "https://s3-us-west-2.amazonaws.com/hm-registration/successsignin.html",
                "country_code": "0",
                "device_id": "02:00:00:00:00:00",
                "device_model": "android_phone",
                "app_version": "4.2.0",
                "source": "com.huami.watch.hmwatchmanager",
                "state": "REDIRECTION",
                "token": "access",
            },
            headers=_HEADERS,
        )

        if resp.status_code not in (200, 302):
            raise ValueError(f"登录失败：HTTP {resp.status_code}")

        data = resp.json()
        token_info = data.get("token_info", {})
        token = token_info.get("login_token") or token_info.get("access_token")

        if not token:
            error_msg = data.get("message") or data.get("error_message") or "账号或密码错误"
            raise ValueError(f"登录失败：{error_msg}")

        # Step 2: Fetch device list with auth keys
        resp2 = await client.get(
            _DEVICE_URL,
            headers={**_HEADERS, "apptoken": token},
        )
        resp2.raise_for_status()
        payload = resp2.json()

        devices_raw = payload if isinstance(payload, list) else payload.get("devices", [])

        result = []
        for d in devices_raw:
            mac = d.get("macAddress") or d.get("mac_address")
            auth_key = d.get("hmac") or d.get("auth_key")
            name = d.get("deviceName") or d.get("name") or "Unknown Device"
            if mac and auth_key:
                mac = mac.upper().replace("-", ":")
                auth_key = auth_key.replace(" ", "").lower()
                result.append({"mac": mac, "name": name, "auth_key": auth_key})

        return result
