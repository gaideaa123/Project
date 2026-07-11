from __future__ import annotations

from unittest.mock import patch

import tiktok_login
import tiktok_session_bundle

class Context:
 def __init__(self,rows=None):self.rows=list(rows or []);self.added=[];self.cleared=[]
 def cookies(self,urls=None):
  merged={row["name"]:row for row in self.rows}
  merged.update({row["name"]:row for row in self.added})
  return list(merged.values())
 def add_cookies(self,rows):self.added.extend(rows)
 def clear_cookies(self,name=None):self.cleared.append(name);self.rows=[row for row in self.rows if row.get("name")!=name]

def main()->None:
 raw="abcdefghijklmnop"
 assert tiktok_session_bundle.parse(raw)=={"sessionid":raw}
 assert tiktok_session_bundle.loads('{"sessionid":"abcdefghijklmnop","sessionid_ss":"abcdefghijklmnop"}')=={"sessionid":raw}
 context=Context([{"name":"sid_guard","value":"device-guard"},{"name":"uid_tt","value":"device-uid"}])
 with patch.object(tiktok_login,"load_session_cookies",return_value={"sessionid":raw}):
  assert tiktok_login.bootstrap_session(context,"p")
 assert context.cleared==[]
 assert {row["name"] for row in context.added}=={"sessionid"}
 assert context.cookies()[0]["value"]=="device-guard"
 fabricated=Context([{"name":"sessionid_ss","value":raw},{"name":"sid_guard","value":"keep-me"}])
 with patch.object(tiktok_login,"load_session_cookies",return_value={"sessionid":raw}):
  assert tiktok_login.bootstrap_session(fabricated,"p",force=True)
 assert fabricated.cleared==["sessionid_ss"]
 assert any(row.get("name")=="sid_guard" for row in fabricated.rows)
 print("OK: session bootstrap cihaz çerezlerini koruyor ve sahte alias üretmiyor")

if __name__=="__main__":main()
