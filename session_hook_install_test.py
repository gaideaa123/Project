from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import tiktok_login

class Context:
 def __init__(self):self.added=[]
 def cookies(self,urls=None):return list(self.added)
 def add_cookies(self,rows):self.added.extend(rows)
 def close(self):pass

def main()->None:
 context=Context();calls=[]
 uploader=SimpleNamespace(launch_context=lambda playwright,profile:(calls.append(profile),context)[1],prepare_upload=lambda request:None)
 with patch.object(tiktok_login,"load_session_cookies",return_value={"sessionid":"abcdefghijklmnop"}),patch.object(tiktok_login.preflight_hook,"install"):
  tiktok_login.install(uploader)
  launched=uploader.launch_context(object(),"hesap-1")
 assert launched is context and calls==["hesap-1"]
 assert context.added and context.added[0]["name"]=="sessionid"
 assert getattr(uploader,"_signaldesk_login_installed",False)
 assert not hasattr(uploader,"confirm_publish_dialog")
 print("OK: opsiyonel uploader API'leri yokken bile Session ID launch hooku kuruldu")

if __name__=="__main__":main()
