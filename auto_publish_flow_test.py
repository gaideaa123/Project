from __future__ import annotations

from unittest.mock import patch

import auto_publish_flow

class Button:
 @property
 def first(self): return self
 def is_visible(self,timeout=0): return True
 def is_enabled(self): return True

class Empty:
 @property
 def first(self): return self
 def count(self): return 0

class Body:
 def __init__(self,page): self.page=page
 def inner_text(self,timeout=0): return self.page.texts[self.page.index]

class Page:
 def __init__(self,texts): self.texts=list(texts); self.index=0; self.waits=[]; self.button=Button()
 def is_closed(self): return False
 def wait_for_timeout(self,value): self.waits.append(value); self.index=min(self.index+1,len(self.texts)-1)
 def locator(self,selector): return Body(self) if selector=='body' else Empty()
 def get_by_role(self,role,name=None): return self.button if role=='button' else Empty()


def main() -> None:
 page=Page(["Video yükleniyor 70% İçerik kontrolü sürüyor","İçerik kontrolü sürüyor","Kontrol tamamlandı","Kontrol tamamlandı","Kontrol tamamlandı"])
 with patch.object(auto_publish_flow.time,"monotonic",side_effect=range(100)):
  assert auto_publish_flow.wait_for_checks_complete(page,timeout_seconds=90) is page.button
 assert len(page.waits)>=4

 blocked=Page(["Özgün olmayan, düşük kaliteli ve QR kodlu içerik. Yine de paylaşabilirsiniz."])
 with patch.object(auto_publish_flow.time,"monotonic",side_effect=range(20)):
  try:
   auto_publish_flow.wait_for_checks_complete(blocked,timeout_seconds=10)
   raise AssertionError("Advisory varken yayın devam etmemeliydi")
  except RuntimeError as exc:
   assert "Yine de paylaş" in str(exc) and "seçilmedi" in str(exc)
 assert not hasattr(auto_publish_flow,"handle_advisory_dialog")
 print("OK: kontrol bitince hazır, özgünlük uyarısında fail-closed ve Yine de paylaş yok")

if __name__=='__main__': main()
