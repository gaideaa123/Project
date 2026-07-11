from __future__ import annotations

from types import SimpleNamespace

import published_review_bridge


def main() -> None:
 calls=[];statuses=[]
 def review_error(request,publish=False,approval=None,status=None):
  calls.append((request.profile,publish))
  raise RuntimeError(
   "Gönderi yayınlandı ancak erişim riski görüldü: inceleniyor\n"
   r"Tanı dosyaları: C:\Users\ahmet\AppData\Local\SignalDesk\diagnostics\x"
  )
 uploader=SimpleNamespace(prepare_upload=review_error)
 assert published_review_bridge.install(uploader)
 request=SimpleNamespace(profile="hesap-1")
 assert uploader.prepare_upload(request,publish=True,status=statuses.append) is None
 assert calls==[("hesap-1",True)] and "sıradaki hesaba" in statuses[-1]
 try:uploader.prepare_upload(request,publish=False,status=statuses.append)
 except RuntimeError:pass
 else:raise AssertionError("Yayın modu dışındaki hata yutulmamalı")
 def real_error(request,publish=False,approval=None,status=None):raise RuntimeError("TikTok yayın hatası gösterdi")
 uploader2=SimpleNamespace(prepare_upload=real_error)
 published_review_bridge.install(uploader2)
 try:uploader2.prepare_upload(request,publish=True)
 except RuntimeError:pass
 else:raise AssertionError("Gerçek yayın hatası yutulmamalı")
 print("OK: yayınlanmış inceleniyor sonucu tamamlandı sayılıyor, gerçek hatalar korunuyor")

if __name__=="__main__":main()
