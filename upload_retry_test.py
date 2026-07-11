from __future__ import annotations
from unittest.mock import patch
import auto_publish_flow,upload_state

class Item:
 def __init__(self,text="",visible=True):self.text=text;self.visible=visible;self.clicks=[]
 @property
 def first(self):return self
 def count(self):return 1
 def nth(self,index):return self
 def is_visible(self,timeout=0):return self.visible
 def inner_text(self,timeout=0):return self.text
 def get_attribute(self,name):return self.text if name=="aria-label" else None
 def locator(self,selector):return self
 def get_by_role(self,role,name=None):return self
 def scroll_into_view_if_needed(self,timeout=0):pass
 def click(self,**kwargs):self.clicks.append(kwargs)
 def is_enabled(self):return True
 def evaluate(self,script):return ["1.mp4",1234]
class Empty(Item):
 def count(self):return 0
class Page:
 def __init__(self):self.error=Item("Video yüklenemedi. Daha sonra tekrar deneyin.");self.retry=Item("Tekrar dene");self.publish=Item("Paylaş");self.waits=0;self.mouse=Empty()
 def locator(self,selector):
  if selector=="body":return Item("Video yüklenemedi")
  if selector=='input[type="file"]':return Item()
  if selector=='[role="progressbar"]':return Empty()
  if "error" in selector:return self.error
  return Empty()
 def get_by_role(self,role,name=None):
  pattern=getattr(name,"pattern","") if name else ""
  return self.retry if "tekrar" in pattern.lower() else self.publish
 def is_closed(self):return False
 def wait_for_timeout(self,value):self.waits+=1


def main():
 page=Page();failure=upload_state.visible_upload_failure(page);assert failure
 with patch.object(failure.container,"get_by_role",return_value=page.retry):assert upload_state.click_retry(page,failure)
 assert page.retry.clicks
 sequence=[failure,failure,failure,None,None,None]
 with patch.object(upload_state,"visible_upload_failure",side_effect=sequence),patch.object(upload_state,"click_retry",return_value=True) as retry,patch.object(auto_publish_flow.time,"monotonic",side_effect=range(100)):
  assert auto_publish_flow.wait_for_checks_complete(page,timeout_seconds=30) is page.publish
  retry.assert_called_once()
 print("OK: görünür kalıcı hatada Tekrar dene tıklanıyor ve başarılı akışa geri dönülüyor")
if __name__=="__main__":main()
