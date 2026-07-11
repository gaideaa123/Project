from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock

import navigation_retry

class Page:
 def __init__(self):self.waits=[];self.blank=[]
 def goto(self,url,**kwargs):self.blank.append(url)
 def wait_for_timeout(self,value):self.waits.append(value)

def main()->None:
 calls={"count":0}
 def flaky(page):
  calls["count"]+=1
  if calls["count"]<3:raise RuntimeError("Page.goto: net::ERR_TUNNEL_CONNECTION_FAILED")
 uploader=SimpleNamespace(goto_upload=flaky)
 navigation_retry.install(uploader);page=Page();uploader.goto_upload(page)
 assert calls["count"]==3 and page.waits==[1500,3000] and page.blank==["about:blank","about:blank"]
 assert navigation_retry.is_transient("ERR_CONNECTION_RESET")
 assert not navigation_retry.is_transient("TikTok login failed")
 print("OK: transient SOCKS5 page tunnel is retried three times with bounded backoff")
if __name__=="__main__":main()
