from __future__ import annotations

from unittest.mock import patch

import network_identity
import proxy_health


class Response:
    def __init__(self, payload, status=200):
        self.payload = payload
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self.payload


class FakeSession:
    def __init__(self, proxy_ip="31.59.20.176", geo_fails=True):
        self.proxy_ip = proxy_ip
        self.geo_fails = geo_fails
        self.proxies = {}
        self.headers = {}
        self.trust_env = True

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def get(self, url, timeout=None):
        if "ipapi.co" in url or "ipwho.is" in url:
            if self.geo_fails:
                return Response({"error": True}, 429)
            return Response({"country_code": "TR", "asn": "AS1", "org": "ISP"})
        return Response({"ip": self.proxy_ip})


def main() -> None:
    identity = network_identity.parse_proxy_line("31.59.20.176:6754:user:pass")

    sessions = [FakeSession("198.51.100.10"), FakeSession("31.59.20.176", True)]
    with patch.object(proxy_health, "_session", side_effect=sessions), patch.object(
        proxy_health, "record"
    ):
        result = proxy_health.test(identity, attempts=3)
    assert result.ok, result.detail
    assert result.exit_ip == "31.59.20.176"
    assert result.country_code == ""
    assert "Konum bilgisi alınamadı" in result.detail

    sessions = [FakeSession("198.51.100.10"), FakeSession("31.59.20.176", False)]
    with patch.object(proxy_health, "_session", side_effect=sessions), patch.object(
        proxy_health, "record"
    ):
        enriched = proxy_health.test(identity, attempts=2)
    assert enriched.ok
    assert enriched.country_code == "TR"

    print("OK: Geo servisi çökse bile sağlıklı proxy başarısız sayılmıyor")


if __name__ == "__main__":
    main()
