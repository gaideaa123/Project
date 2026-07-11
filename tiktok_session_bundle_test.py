from __future__ import annotations

import tiktok_session_bundle as bundle


def main() -> None:
 raw="abcdefghijklmnop"
 assert bundle.parse(raw)=={"sessionid":raw,"sessionid_ss":raw}
 header="sessionid=abcdefghijklmnop; sessionid_ss=qrstuvwxyzabcdef; sid_guard=guard-value; uid_tt=uid-value"
 parsed=bundle.parse(header)
 assert parsed["sessionid"]=="abcdefghijklmnop"
 assert parsed["sessionid_ss"]=="qrstuvwxyzabcdef"
 assert parsed["sid_guard"]=="guard-value"
 exported='[{"name":"sessionid","value":"abcdefghijklmnop"},{"name":"uid_tt_ss","value":"uidss"}]'
 parsed=bundle.parse(exported)
 assert parsed["sessionid"]=="abcdefghijklmnop" and parsed["sessionid_ss"]=="abcdefghijklmnop"
 try:bundle.parse("invalid short")
 except ValueError:pass
 else:raise AssertionError("Kısa/geçersiz session kabul edilmemeliydi")
 print("OK: ham session, Cookie başlığı ve JSON cookie paketi doğrulandı")


if __name__=="__main__":main()
