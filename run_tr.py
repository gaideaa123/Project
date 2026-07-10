from __future__ import annotations

import sys
from PySide6.QtCore import QLocale
from PySide6.QtWidgets import (
    QApplication, QDateTimeEdit, QLineEdit, QPlainTextEdit, QProgressBar,
    QSpinBox, QTableWidget,
)

import app_tr


class SignalDeskTurkce(app_tr.TurkceAnaPencere):
    """app.py sürümleri arasında widget adlarını güvenle eşleyen başlatıcı."""

    def _discover_processing_widgets(self) -> None:
        page = self.tabs.widget(1) if self.tabs.count() > 1 else self
        edits = page.findChildren(QLineEdit)
        spins = page.findChildren(QSpinBox)
        bars = page.findChildren(QProgressBar)

        def line(*terms: str) -> QLineEdit | None:
            for field in edits:
                text = f"{field.objectName()} {field.placeholderText()}".casefold()
                if any(term.casefold() in text for term in terms):
                    return field
            return None

        self.master = next(
            (value for value in (
                getattr(self, "master", None), getattr(self, "master_video", None),
                getattr(self, "source", None), getattr(self, "source_video", None),
                line("master", "ana video", "choose video", "source"),
                edits[0] if edits else None,
            ) if isinstance(value, QLineEdit)),
            None,
        )
        self.batch_size = next(
            (value for value in (
                getattr(self, "batch_size", None), getattr(self, "variant_count", None),
                getattr(self, "count", None), spins[0] if spins else None,
            ) if isinstance(value, QSpinBox)),
            None,
        )
        self.progress = next(
            (value for value in (
                getattr(self, "progress", None), getattr(self, "render_progress", None),
                bars[0] if bars else None,
            ) if isinstance(value, QProgressBar)),
            None,
        )

        # Eski/yeni app.py sürümlerinde ilgili alan hiç yoksa çökmek yerine oluştur.
        layout = page.layout()
        if self.master is None:
            self.master = QLineEdit()
            self.master.setPlaceholderText("Ana videoyu seçin")
            if layout:
                layout.addWidget(self.master)
        if self.batch_size is None:
            self.batch_size = QSpinBox()
            if layout:
                layout.addWidget(self.batch_size)
        if self.progress is None:
            self.progress = QProgressBar()
            if layout:
                layout.addWidget(self.progress)

        self.batch_size.setRange(1, 100)
        self.batch_size.setSuffix(" varyant")

    def _uyumluluk_eslemelerini_kur(self) -> None:
        lines = self.findChildren(QLineEdit)
        spins = self.findChildren(QSpinBox)
        dates = self.findChildren(QDateTimeEdit)
        tables = self.findChildren(QTableWidget)
        consoles = self.findChildren(QPlainTextEdit)

        def find_line(*terms: str) -> QLineEdit | None:
            for field in lines:
                text = f"{field.placeholderText()} {field.objectName()}".casefold()
                if any(term.casefold() in text for term in terms):
                    return field
            return None

        mappings = {
            "queue_video": find_line("mp4", "deployment asset", "yayınlanacak"),
            "caption": find_line("caption", "açıklama"),
        }
        for name, value in mappings.items():
            if not hasattr(self, name) and value is not None:
                setattr(self, name, value)
        if not hasattr(self, "run_at") and dates:
            self.run_at = dates[0]
        if not hasattr(self, "console") and consoles:
            self.console = consoles[0]
        if not hasattr(self, "accounts") and tables:
            self.accounts = tables[0]
        if not hasattr(self, "jobs") and len(tables) > 1:
            self.jobs = tables[-1]
        if hasattr(self, "run_at"):
            self.run_at.setDisplayFormat("dd.MM.yyyy HH:mm")

    def build_ui(self) -> None:
        super().build_ui()
        self._uyumluluk_eslemelerini_kur()


def main() -> int:
    loader = getattr(app_tr, "ayarlari_yukle", None) or getattr(app_tr, "kayitli_ayarlari_ortama_yukle", None)
    if callable(loader):
        loader()
    qt = QApplication(sys.argv)
    qt.setApplicationName("SignalDesk Ajans Paneli")
    qt.setOrganizationName("SignalDesk")
    qt.setStyle("Fusion")
    QLocale.setDefault(QLocale(QLocale.Turkish, QLocale.Turkey))
    window = SignalDeskTurkce()
    window.show()
    return qt.exec()


if __name__ == "__main__":
    raise SystemExit(main())
