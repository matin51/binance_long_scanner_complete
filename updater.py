import requests

CURRENT_VERSION = "1.0.0"
UPDATE_JSON_URL = "https://githubusercontent.com"

def check_app_update():
    try:
        resp = requests.get(UPDATE_JSON_URL, timeout=8)
        if resp.status_code == 200:
            data = resp.json()
            latest_version = str(data.get("version", "")).strip()
            if latest_version and latest_version != CURRENT_VERSION:
                return {
                    "version": latest_version,
                    "notes": data.get("notes", "Bug fixes and scanner improvements."),
                    "windows_url": data.get("windows_url", ""),
                    "android_url": data.get("android_url", "")
                }
    except Exception:
        pass
    return None
