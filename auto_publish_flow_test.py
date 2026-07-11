from __future__ import annotations

import auto_publish_flow


def main() -> None:
    warning = (
        "Paylaşmaya devam edilsin mi? Telif hakkı kontrolü eksik. "
        "Videonuzu hâlâ potansiyel sorunlar bakımından kontrol ediyoruz. "
        "İptal Hemen paylaş"
    )
    assert auto_publish_flow.INCOMPLETE_CHECK_DIALOG.search(warning)
    assert auto_publish_flow.DIALOG_CANCEL.fullmatch("İptal")
    assert auto_publish_flow.DIALOG_CANCEL.fullmatch("Kapat")
    assert not auto_publish_flow.DIALOG_CANCEL.fullmatch("Hemen paylaş")
    assert auto_publish_flow.CHECK_COMPLETE.search("İçerik kontrolü: Sorun tespit edilmedi")
    print("OK: uyarıda İptal/Kapat seçiliyor, Hemen paylaş seçilmiyor")


if __name__ == "__main__":
    main()
