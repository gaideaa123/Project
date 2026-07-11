from __future__ import annotations

import auto_publish_flow as flow


def main() -> None:
 both = (
  "Müzik telif hakkı kontrolü Sorun tespit edilmedi. "
  "İçerik kontrolü (hafif) Sorun tespit edilmedi."
 )
 assert flow._all_check_rows_complete(both)
 assert not flow._all_check_rows_complete("İçerik kontrolü Sorun tespit edilmedi")
 assert not flow._all_check_rows_complete("Müzik telif hakkı kontrolü Sorun tespit edilmedi")
 assert flow.CHECK_PENDING.search("Telif hakkı kontrolü eksik")
 assert flow.REPEATED_DIALOG_COOLDOWN_SECONDS >= 10
 assert not hasattr(flow, "MAX_INCOMPLETE_DIALOG_RETRIES")
 print("OK: tekrarlanan uyarı limitle durmuyor; iki kontrol tamamlanana kadar bekliyor")


if __name__ == "__main__":
 main()
