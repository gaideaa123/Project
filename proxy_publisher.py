from __future__ import annotations

"""TikTok API publisher that routes each account through its fixed tested proxy."""

from datetime import timedelta
from pathlib import Path
from typing import Any

import requests

import app as core
import network_identity
import proxy_health


class ProxyAwareTikTokPublisher(core.TikTokPublisher):
    def _network(self, account: dict[str, Any]) -> dict[str, str] | None:
        profile = str(account.get("profile_name") or account.get("name") or "").strip()
        identity = network_identity.load(profile)
        if not identity.server:
            return None
        proxy_health.require_healthy(identity)
        return network_identity.requests_proxies(identity)

    def _request(self, method: str, url: str, account: dict[str, Any], **kwargs: Any) -> requests.Response:
        proxies = self._network(account)
        if proxies:
            kwargs["proxies"] = proxies
        return requests.request(method, url, **kwargs)

    def token(self, account: dict[str, Any]) -> str:
        access, refresh = self.secrets.get(account["id"])
        if not access:
            raise RuntimeError("No access token is stored for this profile")
        if core.from_iso(account["token_expires_at"]) > core.now_utc() + timedelta(minutes=5):
            return access
        client_key = core.os.getenv("TIKTOK_CLIENT_KEY", "").strip()
        client_secret = core.os.getenv("TIKTOK_CLIENT_SECRET", "").strip()
        if not client_key or not client_secret or not refresh:
            raise RuntimeError(
                "Token refresh requires TIKTOK_CLIENT_KEY, TIKTOK_CLIENT_SECRET, and a refresh token"
            )
        response = self._request(
            "POST",
            f"{core.TIKTOK_API}/v2/oauth/token/",
            account,
            data={
                "client_key": client_key,
                "client_secret": client_secret,
                "grant_type": "refresh_token",
                "refresh_token": refresh,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=45,
        )
        payload = self._json(response)
        access = payload["access_token"]
        self.secrets.set(account["id"], access, payload.get("refresh_token", refresh))
        self.registry.update_account(
            account["id"],
            token_expires_at=core.to_iso(
                core.now_utc() + timedelta(seconds=int(payload.get("expires_in", 3600)))
            ),
        )
        return access

    def publish(self, account: dict[str, Any], job: dict[str, Any], signals: core.ThreadSignals) -> str:
        video = Path(job["video_path"])
        if not video.is_file():
            raise FileNotFoundError(video)
        token = self.token(account)
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json; charset=UTF-8",
        }
        info = self._json(
            self._request(
                "POST",
                f"{core.TIKTOK_API}/v2/post/publish/creator_info/query/",
                account,
                headers=headers,
                json={},
                timeout=45,
            )
        ).get("data", {})
        choices = info.get("privacy_level_options", [])
        privacy = "SELF_ONLY" if "SELF_ONLY" in choices or not choices else choices[0]
        size = video.stat().st_size
        chunk_size, chunk_count = self.chunk_plan(size)
        signals.log.emit(f"Initializing official upload for {account['profile_name']}")
        initialized = self._json(
            self._request(
                "POST",
                f"{core.TIKTOK_API}/v2/post/publish/video/init/",
                account,
                headers=headers,
                json={
                    "post_info": {
                        "title": job["caption"][:2200],
                        "privacy_level": privacy,
                        "disable_duet": False,
                        "disable_comment": False,
                        "disable_stitch": False,
                        "video_cover_timestamp_ms": 1000,
                    },
                    "source_info": {
                        "source": "FILE_UPLOAD",
                        "video_size": size,
                        "chunk_size": chunk_size,
                        "total_chunk_count": chunk_count,
                    },
                },
                timeout=45,
            )
        ).get("data", {})
        upload_url = initialized.get("upload_url")
        publish_id = initialized.get("publish_id")
        if not upload_url or not publish_id:
            raise RuntimeError("TikTok did not return an upload URL and publish ID")

        sent = 0
        with video.open("rb") as handle:
            for index in range(chunk_count):
                amount = size - sent if index == chunk_count - 1 else min(chunk_size, size - sent)
                body = handle.read(amount)
                end = sent + len(body) - 1
                response = self._request(
                    "PUT",
                    upload_url,
                    account,
                    data=body,
                    headers={
                        "Content-Type": "video/mp4",
                        "Content-Length": str(len(body)),
                        "Content-Range": f"bytes {sent}-{end}/{size}",
                    },
                    timeout=180,
                )
                if not response.ok:
                    raise RuntimeError(
                        f"Chunk upload failed ({response.status_code}): {response.text[:500]}"
                    )
                sent = end + 1
                signals.progress.emit(round(sent * 100 / size))
                signals.log.emit(f"Uploaded chunk {index + 1}/{chunk_count}")
        return str(publish_id)
