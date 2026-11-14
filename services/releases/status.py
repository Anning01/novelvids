import asyncio
import time
from pathlib import Path

import httpx
from fastapi import HTTPException

from services.releases import LOCAL, REPO, TAG, version_key

_latest = None
_checked = 0.0
_lock = asyncio.Lock()
SOCKET = Path("/run/novelvids-update/control.sock")


async def latest_release():
    global _latest, _checked
    async with _lock:
        if _checked and time.monotonic() - _checked < 300:
            return _latest
        try:
            async with httpx.AsyncClient(timeout=5, follow_redirects=True) as client:
                response = await client.get(f"https://api.github.com/repos/{REPO}/releases/latest")
                response.raise_for_status()
                release = response.json()
                tag = release["tag_name"]
                if not TAG.fullmatch(tag) or release["draft"] or release["prerelease"]:
                    raise ValueError("Expected stable release")
                manifest_url = next((asset["browser_download_url"] for asset in release.get("assets", [])
                                     if asset["name"] == "release.json"),
                                    f"https://raw.githubusercontent.com/{REPO}/{tag}/release.json")
                response = await client.get(manifest_url)
                response.raise_for_status()
                manifest = response.json()
                if manifest["version"] != tag[1:]:
                    raise ValueError("Tag mismatch")
                minimum = manifest["minimum"]
                required = [key for key, value in minimum.items() if version_key(value) > version_key(LOCAL["version"])]
                _latest = dict(version=tag[1:], required=required, summary=str(manifest["summary"])[:240],
                               summary_en=str(manifest["summary_en"])[:240], online=manifest.get("update_format") == 1)
        except (httpx.HTTPError, ValueError, KeyError, TypeError, AttributeError):
            pass  # Keep the last verified release when the feed is unavailable.
        _checked = time.monotonic()
        return _latest


async def updater(method="GET", version=None):
    if SOCKET.is_socket():
        try:
            async with httpx.AsyncClient(transport=httpx.AsyncHTTPTransport(uds=str(SOCKET)), timeout=3) as client:
                response = await client.request(method, "http://localhost/update", json={"version":version} if version else None)
                response.raise_for_status()
                return response.json()
        except httpx.HTTPError:
            pass
    if method == "POST":
        raise HTTPException(409, "更新服务未就绪，请检查部署主机上的更新服务")
    return None
