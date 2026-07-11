from __future__ import annotations

from unittest.mock import Mock, patch

import auto_publish_flow

class Page:
 def __init__(self, texts, enabled=True):
  self.texts=list(texts); self.enabled=enabled; self.index=0; self.waits=[]
 def is_closed(self): return False
 def wait_for_timeout(self, value): self.waits.append(value); self.index=min(self.index+1,len(self.texts)-1)
 def locator(self, selector):
  if selector=='body': return Body(self)
  if selector=='[role="progressbar"]': return Empty()
  return Empty()
 def get_by_role(self, role, name=None): return Button(self) if role=='button' else Empty()

class Body:
 def __init__(self,page): self.page=page
 def inner_text(self,timeout=0): return self.page.texts[self.page.index]
class Empty:
 @property
 def first(self): return self
 def count(self): return 0
class Button:
 def __init__(self,page): self.page=page
 @property
 def first(self): return self
 def is_visible(self,timeout=0): return True
 def is_enabled(self): return self.page.enabled


def main() -> None:
 page=Page(["Video yükleniyor 70% İçerik kontrolü sürüyor","İçerik kontrolü sürüyor","Kontrol tamamlandı","Kontrol tamamlandı","Kontrol tamamlandı"])
 with patch.object(auto_publish_flow.time,"monotonic",side_effect=range(100)):
  button=auto_publish_flow.wait_for_checks_complete(page,timeout_seconds=90)
  assert isinstance(button,Button)
  assert len(page.waits)>=4

 advisory=RuntimeError("dummy")
 assert auto_publish_flow.ADVISORY.search("Özgün olmayan, düşük kaliteli ve QR kodlu içerik")
 assert auto_publish_flow.CONTINUE_BUTTON.fullmatch("Yine de paylaş")
 assert auto_publish_flow.CHECK_PENDING.search("İçerik kontrolü sürüyor")
 assert not auto_publish_flow.CHECK_PENDING.search("İçerik kontrolü tamamlandı")
 print("OK: kontrol bitişi bekleniyor, kalite uyarısı ve Yine de paylaş tanınıyor")

if __name__=='__main__': main()
