from __future__ import annotations
from unittest.mock import MagicMock,patch
import ab_diagnostics,profile_integrity,proxy_health,publication_pacing

def check(v,m):
    if not v:raise AssertionError(m)
    print("OK:",m)
def main():
    check(publication_pacing.classify(RuntimeError("connection timeout"))=="transient","geçici ağ hatası sınıflanıyor")
    check(publication_pacing.classify(RuntimeError("account restricted"))!="transient","policy hatası retry edilmiyor")
    check(publication_pacing.should_retry(RuntimeError("proxy timeout"),0),"sınırlı transient retry")
    check(not publication_pacing.should_retry(RuntimeError("private audience"),0),"privacy hatası retry edilmiyor")
    context=MagicMock();response=MagicMock();response.ok=True;response.json.return_value={"ip":"1.2.3.4"};context.request.get.return_value=response
    identity=MagicMock();healthy=proxy_health.ProxyHealth("x",True,"1.2.3.4","TR",100,"2099-01-01T00:00:00+00:00")
    with patch.object(proxy_health,"require_healthy",return_value=healthy):check(proxy_health.verify_browser_context(context,identity).exit_ip=="1.2.3.4","aynı context çıkış IP doğrulaması")
    check(profile_integrity.secret_fingerprint("secret")!="secret","session manifestte hashleniyor")
    result=ab_diagnostics.ABResult("p","web",0,True,True,"now");check(result.channel=="web","A/B veri modeli")
    print("\nİLERİ RİSK KONTROLLERİ GEÇTİ")
if __name__=="__main__":main()
