from __future__ import annotations

import os
import sys
from pathlib import Path

from PySide6.QtCore import QLocale
from PySide6.QtWidgets import (
    QApplication, QDateTimeEdit, QLineEdit, QPlainTextEdit, QSpinBox,
    QTableWidget,
)

import app
import app_tr


class SignalDeskTurkce(app_tr.TurkceAnaPencere):
    """app.py sürümleri arasında widget adlarını otomatik eşleyen güvenli başlatıcı."""

    def build_ui(self) -> None:
        super().build_ui()
        self._uyumluluk_eslemelerini_kur()

    def _uyumluluk_eslemelerini_kur(self) -> None:
        satirlar = self.findChildren(QLineEdit)
        spinler = self.findChildren(QSpinBox)
        tarihler = self.findChildren(QDateTimeEdit)
        tablolar = self.findChildren(QTableWidget)
        konsollar = self.findChildren(QPlainTextEdit)

        def satir_bul(*kelimeler: str) -> QLineEdit | None:
            for alan in satirlar:
                metin = (alan.placeholderText() + " " + alan.objectName()).casefold()
                if any(kelime.casefold() in metin for kelime in kelimeler):
                    return alan
            return None

        if not hasattr(self, "output_dir"):
            alan = satir_bul("output folder", "çıktı klasörü", "output")
            if alan is not None:
                self.output_dir = alan
        if not hasattr(self, "master"):
            alan = satir_bul("master", "ana medya", "ana dosya")
            if alan is not None:
                self.master = alan
        if not hasattr(self, "queue_video"):
            alan = satir_bul("mp4", "deployment asset", "yayınlanacak")
            if alan is not None:
                self.queue_video = alan
        if not hasattr(self, "caption"):
            alan = satir_bul("caption", "açıklama")
            if alan is not None:
                self.caption = alan
        if not hasattr(self, "batch_size") and spinler:
            self.batch_size = spinler[0]
        if not hasattr(self, "run_at") and tarihler:
            self.run_at = tarihler[0]
        if not hasattr(self, "console") and konsollar:
            self.console = konsollar[0]
        if not hasattr(self, "accounts") and tablolar:
            self.accounts = tablolar[0]
        if not hasattr(self, "jobs") and len(tablolar) > 1:
            self.jobs = tablolar[-1]

        if hasattr(self, "output_dir"):
            self.output_dir.setReadOnly(False)
            self.output_dir.setClearButtonEnabled(True)
            self.output_dir.setPlaceholderText("Çıktı klasörünü seçin veya tam yolu yazın")
        if hasattr(self, "batch_size"):
            self.batch_size.setSuffix(" çıktı")
        if hasattr(self, "run_at"):
            self.run_at.setDisplayFormat("dd.MM.yyyy HH:mm")

    def choose_output(self) -> None:
        self._uyumluluk_eslemelerini_kur()
        return super().choose_output()

    def choose_master(self) -> None:
        self._uyumluluk_eslemelerini_kur()
        return super().choose_master()


def main() -> int:
    app_tr.kayitli_ayarlari_ortama_yukle()
    qt = QApplication(sys.argv)
    qt.setApplicationName("SignalDesk Ajans Paneli")
    qt.setOrganizationName("SignalDesk")
    qt.setStyle("Fusion")
    QLocale.setDefault(QLocale(QLocale.Turkish, QLocale.Turkey))
    pencere = SignalDeskTurkce()
    pencere.show()
    return qt.exec()


if __name__ == "__main__":
    raise SystemExit(main())
