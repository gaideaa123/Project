from __future__ import annotations

from unittest.mock import Mock, patch

import auto_publish_flow

class Button:
 def __init__(self,page=None): self.page=page; self.clicks=[]
 @property
 def first(self): return self
 def is_visible(self,timeout=0): return True
 def is_enabled(self): return True
 def scroll_into_view_if_needed(self,timeout=0): pass
 def click(self,**kwargs): self.clicks.append(kwargs)

class Empty:
 @property
 def first(self): return self
 def count(self): return 0

class Body:
 def __init__(self,page): self.page=page
 def inner_text(self,timeout=0): return self.page.texts[self.page.index]

class CheckPage:
 def __init__(self,texts): self.texts=list(texts); self.index=0; self.waits=[]; self.button=Button(self)
 def is_closed(self): return False
 def wait_for_timeout(self,value): self.waits.append(value); self.index=min(self.index+1,len(self.texts)-1)
 def locator(self,selector):
  if selector=='body': return Body(self)
  return Empty()
 def get_by_role(self,role,name=None): return self.button if role=='button' else Empty()

class Dialog:
 def __init__(self,text,button): self.text=text; self.button=button
 def is_visible(self,timeout=0): return True
 def inner_text(self,timeout=0): return self.text
 def get_by_role(self,role,name=None): return self.button

class DialogList:
 def __init__(self,dialog): self.dialog=dialog
 def count(self): return 1
 def nth(self,index): return self.dialog

class AdvisoryPage:
 def __init__(self):
  self.button=Button(self)
  self.dialog=Dialog("Özgün olmayan, düşük kaliteli ve QR kodlu içerik. Yine de paylaşabilirsiniz.",self.button)
  self.mouse=Mock(); self.waits=[]
 def locator(self,selector): return DialogList(self.dialog)
 def wait_for_timeout(self,value): self.waits.append(value)


def main() -> None:
 page=CheckPage(["Video yükleniyor 70% İçerik kontrolü sürüyor","İçerik kontrolü sürüyor","Kontrol tamamlandı","Kontrol tamamlandı","Kontrol tamamlandı"])
 with patch.object(auto_publish_flow.time,"monotonic",side_effect=range(100)):
  assert auto_publish_flow.wait_for_checks_complete(page,timeout_seconds=90) is page.button
 assert len(page.waits)>=4

 advisory=AdvisoryPage()
 with patch.object(auto_publish_flow.time,"monotonic",side_effect=range(20)):
  assert auto_publish_flow.handle_advisory_dialog(advisory,timeout_seconds=10)
 assert len(advisory.button.clicks)==1
 assert auto_publish_flow.ADVISORY.search("Özgün olmayan, düşük kaliteli ve QR kodlu içerik")
 assert auto_publish_flow.CONTINUE_BUTTON.fullmatch("Yine de paylaş")
 assert not auto_publish_flow.CHECK_PENDING.search("İçerik kontrolü tamamlandı")
 print("OK: kontrol bitişi bekleniyor ve doğrulanmış kalite uyarısında Yine de paylaş tıklanıyor")

if __name__=='__main__': main()
