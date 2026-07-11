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

    completed = (
        "Müzik telif hakkı kontrolü Sorun tespit edilmedi. "
        "İçerik kontrolü Sorun tespit edilmedi."
    )
    assert auto_publish_flow.CHECK_COMPLETE.search(completed)
    assert not auto_publish_flow.CHECK_PENDING.search(completed)
    assert auto_publish_flow.CHECK_PENDING.search("İçerik kontrolü sürüyor")
    assert auto_publish_flow.CHECK_PENDING.search("Copyright check is still in progress")
    assert auto_publish_flow.MAX_INCOMPLETE_DIALOG_RETRIES > 0

    print("OK: İptal/Kapat seçiliyor, Hemen paylaş dışlanıyor ve tamamlanma kanıtı doğrulanıyor")


if __name__ == "__main__":
    main()
