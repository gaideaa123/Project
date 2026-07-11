from __future__ import annotations

from unittest.mock import patch

import auto_publish_flow
import upload_state

class Item:
 def __init__(self,text="",visible=True):self.text=text;self.visible=visible
 @property
 def first(self):return self
 def is_visible(self,timeout=0):return self.visible
 def inner_text(self,timeout=0):return self.text
 def get_attribute(self,name):return None
 def is_enabled(self):return True
 def evaluate(self,script):return ["1.mp4",1234]
class Collection:
 def __init__(self,items):self.items=items
 @property
 def first(self):return self.items[0]
 def count(self):return len(self.items)
 def nth(self,index):return self.items[index]
class Page:
 def __init__(self,error_visible):self.error=Item("Video yüklenemedi",error_visible);self.button=Item("Paylaş",True);self.waits=0
 def locator(self,selector):
  if selector=="body":return Item("Video yüklenemedi",True)
  if selector=='input[type="file"]':return Collection([Item()])
  if selector=='[role="progressbar"]':return Collection([])
  if "error" in selector:return Collection([self.error])
  return Collection([])
 def get_by_role(self,role,name=None):return self.button
 def is_closed(self):return False
 def wait_for_timeout(self,value):self.waits+=1


def main()->None:
 hidden=Page(False)
 assert upload_state.visible_upload_failure(hidden) is None
 with patch.object(auto_publish_flow.time,"monotonic",side_effect=range(100)):
  assert auto_publish_flow.wait_for_checks_complete(hidden,timeout_seconds=20) is hidden.button
 visible=Page(True)
 assert upload_state.visible_upload_failure(visible).text=="Video yüklenemedi"
 with patch.object(auto_publish_flow.time,"monotonic",side_effect=range(100)):
  try:auto_publish_flow.wait_for_checks_complete(visible,timeout_seconds=20);raise AssertionError("Kalıcı görünür hata kabul edildi")
  except RuntimeError as exc:
   assert "görünür ve kalıcı" in str(exc) and "1.mp4" in str(exc)
 print("OK: gizli hata şablonu yok sayılıyor, görünür kalıcı hata doğrulanıyor")

if __name__=="__main__":main()
