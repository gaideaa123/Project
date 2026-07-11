from __future__ import annotations
from unittest.mock import patch
import network_identity,proxy_health,publication_pacing,publication_guard

def check(v,m):
    if not v:raise AssertionError(m)
    print("OK:",m)
def main():
    identity=network_identity.parse_proxy_line("127.0.0.1:8080:u:p")
    with patch.object(proxy_health,"latest",return_value=None):
        try:proxy_health.require_healthy(identity)
        except proxy_health.ProxyHealthError:check(True,"test edilmemiş proxy engelleniyor")
        else:raise AssertionError("test edilmemiş proxy kabul edildi")
    good=proxy_health.ProxyHealth(proxy_health.fingerprint(identity),True,"1.2.3.4","TR",120,"2099-01-01T00:00:00+00:00")
    with patch.object(proxy_health,"latest",return_value=good):check(proxy_health.require_healthy(identity).exit_ip=="1.2.3.4","sağlıklı proxy kabul ediliyor")
    check(publication_pacing.get_seconds()>=30,"minimum pacing zorunlu")
    check(publication_guard.POST_REVIEW.search("Video is under review") is not None,"yayın sonrası inceleme yakalanıyor")
    check(publication_guard.POST_SUCCESS.search("Upload complete") is None,"upload complete başarı sayılmıyor")
    print("\nPROXY TEST VE RİSK KONTROLLERİ GEÇTİ")
if __name__=="__main__":main()
