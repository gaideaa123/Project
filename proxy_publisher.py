from __future__ import annotations

"""Compatibility adapters for account-scoped, tested proxy routing."""

from datetime import timedelta
from pathlib import Path
from typing import Any

import requests

import app as core
import network_identity
import proxy_health


def _account_name(account: dict[str, Any]) -> str:
    return str(account.get("profile_name") or account.get("name") or "").strip()


def _proxies_for(account: dict[str, Any]) -> dict[str, str] | None:
    identity = network_identity.load(_account_name(account))
    if not identity.server:
        return None
    proxy_health.require_healthy(identity)
    return network_identity.requests_proxies(identity)


if hasattr(core, "TikTokPublisher"):
    class ProxyAwareTikTokPublisher(core.TikTokPublisher):
        def _request(
            self, method: str, url: str, account: dict[str, Any], **kwargs: Any
        ) -> requests.Response:
            proxies = _proxies_for(account)
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

        def publish(
            self, account: dict[str, Any], job: dict[str, Any], signals: core.ThreadSignals
        ) -> str:
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
            signals.log.emit(f"Initializing official upload for {_account_name(account)}")
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
                    if not body:
                        raise RuntimeError("Video upload sırasında beklenmedik şekilde sona erdi")
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
else:
    ProxyAwareTikTokPublisher = None


if hasattr(core, "TikTokClient"):
    class ProxyAwareTikTokClient(core.TikTokClient):
        """Adapter for the newer app.py architecture using ResilientHttp."""

        def _activate_proxy(self, account: dict[str, Any]) -> None:
            proxies = _proxies_for(account) or {}
            for session_name in ("session", "direct"):
                session = getattr(self.http, session_name, None)
                if session is not None:
                    session.proxies.clear()
                    session.proxies.update(proxies)

        def access_token(self, account: dict[str, Any]) -> str:
            self._activate_proxy(account)
            return super().access_token(account)

        def upload(self, account: dict[str, Any], *args: Any, **kwargs: Any) -> str:
            self._activate_proxy(account)
            return super().upload(account, *args, **kwargs)

        def poll(self, account: dict[str, Any], *args: Any, **kwargs: Any) -> str:
            self._activate_proxy(account)
            return super().poll(account, *args, **kwargs)
else:
    ProxyAwareTikTokClient = None


def install_proxy_backend(window: Any) -> str:
    """Install the matching proxy backend without assuming one app.py generation."""
    if ProxyAwareTikTokPublisher is not None and all(
        hasattr(window, name) for name in ("registry", "secrets")
    ):
        window.publisher = ProxyAwareTikTokPublisher(window.registry, window.secrets)
        return "publisher"
    if ProxyAwareTikTokClient is not None and all(
        hasattr(window, name) for name in ("registry", "vault")
    ):
        client = ProxyAwareTikTokClient(window.registry, window.vault)
        for attribute in ("client", "tiktok", "publisher"):
            if hasattr(window, attribute):
                setattr(window, attribute, client)
                return attribute
        window.client = client
        return "client"
    return "none"
