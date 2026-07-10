from __future__ import annotations

import sys
from datetime import timedelta
from pathlib import Path

from PySide6.QtCore import QLocale, Qt
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDateTimeEdit, QFileDialog,
    QLabel, QLineEdit, QMessageBox, QPushButton, QSpinBox, QTableWidget,
    QTableWidgetItem,
)

import app as core


METINLER = {
    "SIGNALDESK / AGENCY OPERATIONS": "SIGNALDESK / AJANS OPERASYONLARI",
    "Ship content with a paper trail.": "İçeriği kayıtlı, kontrollü ve güvenli yayınla.",
    "READY": "HAZIR",
    "Profile Manager": "Profil Yönetimi",
    "Batch Processing": "Toplu Medya İşleme",
    "Deployment Queue": "Yayın Kuyruğu",
    "Connect an official channel": "Resmî bir kanal bağla",
    "OAuth tokens stay in the operating system keychain. JSON never contains credentials.":
        "OAuth belirteçleri işletim sisteminin güvenli kasasında tutulur. JSON dosyasına kimlik bilgisi yazılmaz.",
    "Profile": "Profil",
    "Platform": "Platform",
    "Access token": "Erişim belirteci",
    "Refresh token": "Yenileme belirteci",
    "Network gateway": "Ağ geçidi",
    "Add profile": "Profil ekle",
    "Authorized profiles": "Yetkilendirilmiş profiller",
    "Remove selected": "Seçileni kaldır",
    "Token": "Belirteç",
    "Network": "Ağ",
    "Added": "Eklenme",
    "H.264 rendition batch": "H.264 çıktı paketi",
    "CRF 20 to 23, normalized H.264/AAC, mobile sharpening, optional micro-grain, and loudness normalization.":
        "CRF 20-23, standart H.264/AAC, mobil ekran keskinliği, isteğe bağlı hafif film dokusu ve ses yüksekliği normalizasyonu.",
    "Select master": "Ana dosyayı seç",
    "Select folder": "Çıktı klasörünü seç",
    "Start batch": "Toplu işlemi başlat",
    "Processing log": "İşlem günlüğü",
    "Browse": "Gözat",
    "Deployment time": "Yayın zamanı",
    "Caption": "Açıklama",
    "Repeat daily": "Her gün tekrarla",
    "Queue deployment": "Yayını kuyruğa ekle",
    "23-hour guarded pipeline": "23 saat korumalı yayın hattı",
    "Run due jobs": "Zamanı gelenleri çalıştır",
    "Asset": "Medya",
    "Next run": "Sonraki çalışma",
    "Cadence": "Tekrar",
    "State": "Durum",
    "Publish ID": "Yayın kimliği",
    "TikTok": "TikTok",
}

YER_TUTUCULAR = {
    "Brand Europe": "Marka Türkiye",
    "Official OAuth access token": "Resmî OAuth erişim belirteci",
    "Official OAuth refresh token": "Resmî OAuth yenileme belirteci",
    "Optional approved corporate gateway": "İsteğe bağlı, onaylı kurumsal ağ geçidi",
    "Master media file": "Ana medya dosyası",
    "Output folder": "Çıktı klasörü",
    "Compliant MP4 rendition": "Standartlara uygun MP4 çıktısı",
    "Approved caption": "Onaylanmış gönderi açıklaması",
}

HATA_BASLIKLARI = {
    "Missing details": "Eksik bilgi",
    "Could not add profile": "Profil eklenemedi",
    "Nothing selected": "Seçim yapılmadı",
    "Missing paths": "Dosya yolları eksik",
    "Batch failed": "Toplu işlem başarısız",
    "Incomplete deployment": "Yayın bilgileri eksik",
    "Could not queue deployment": "Yayın kuyruğa eklenemedi",
    "Deployment is active": "Yayın işlemi sürüyor",
    "Deployment failed": "Yayın işlemi başarısız",
}

PARCA_CEVIRILERI = {
    "Profile name, access token, and refresh token are required":
        "Profil adı, erişim belirteci ve yenileme belirteci zorunludur",
    "Select a profile first": "Önce bir profil seçin",
    "Choose an existing master file and output folder":
        "Var olan bir ana medya dosyası ve çıktı klasörü seçin",
    "Choose a profile, an existing MP4, and a caption":
        "Bir profil, var olan bir MP4 dosyası ve açıklama seçin",
    "Select a deployment first": "Önce bir yayın seçin",
    "Wait for the current network request to finish":
        "Etkin ağ işleminin tamamlanmasını bekleyin",
    "Profile names must be unique": "Profil adları benzersiz olmalıdır",
    "The selected profile no longer exists": "Seçilen profil artık mevcut değil",
    "The queued MP4 file is missing": "Kuyruktaki MP4 dosyası bulunamadı",
    "No access token is stored for this profile": "Bu profil için erişim belirteci kayıtlı değil",
    "The access token expired and no refresh token is stored":
        "Erişim belirtecinin süresi doldu ve yenileme belirteci kayıtlı değil",
    "Set TIKTOK_CLIENT_KEY and TIKTOK_CLIENT_SECRET for refresh":
        "Yenileme için TIKTOK_CLIENT_KEY ve TIKTOK_CLIENT_SECRET değişkenlerini ayarlayın",
    "23-hour guard": "23 saat koruması",
    "another queued deployment for this profile is too close":
        "bu profil için kuyruktaki başka bir yayın zamansal olarak çok yakın",
    "this profile cannot post before": "bu profil şu zamandan önce gönderi paylaşamaz",
}

DURUM_CEVIRILERI = {
    "Ready": "Hazır",
    "Refresh soon": "Yakında yenilenecek",
    "Gateway": "Ağ geçidi",
    "Direct": "Doğrudan",
    "Daily": "Günlük",
    "Once": "Tek sefer",
    "Queued": "Kuyrukta",
    "Running": "Çalışıyor",
    "Failed": "Başarısız",
    "Submitted": "Gönderildi",
}


def cevir(metin: str) -> str:
    sonuc = METINLER.get(metin, metin)
    for kaynak, hedef in PARCA_CEVIRILERI.items():
        sonuc = sonuc.replace(kaynak, hedef)
    return sonuc


class TurkceAnaPencere(core.MainWindow):
    def build_ui(self) -> None:
        super().build_ui()
        self.setWindowTitle("SignalDesk Ajans Paneli")
        self._sabit_metinleri_cevir()

    def _sabit_metinleri_cevir(self) -> None:
        self.tabs.setTabText(0, "Profil Yönetimi")
        self.tabs.setTabText(1, "Toplu Medya İşleme")
        self.tabs.setTabText(2, "Yayın Kuyruğu")

        for etiket in self.findChildren(QLabel):
            etiket.setText(METINLER.get(etiket.text(), etiket.text()))
        for dugme in self.findChildren(QPushButton):
            dugme.setText(METINLER.get(dugme.text(), dugme.text()))
        for kutu in self.findChildren(QCheckBox):
            kutu.setText(METINLER.get(kutu.text(), kutu.text()))
        for alan in self.findChildren(QLineEdit):
            alan.setPlaceholderText(YER_TUTUCULAR.get(alan.placeholderText(), alan.placeholderText()))

        self.accounts.setHorizontalHeaderLabels(["Profil", "Platform", "Belirteç", "Ağ", "Eklenme"])
        self.jobs.setHorizontalHeaderLabels(
            ["Profil", "Medya", "Sonraki çalışma", "Tekrar", "Durum", "Yayın kimliği"]
        )
        self.batch_size.setSuffix(" çıktı")
        self.run_at.setDisplayFormat("dd.MM.yyyy HH:mm")

    def refresh(self) -> None:
        super().refresh()
        self._sabit_metinleri_cevir()
        for row in range(self.accounts.rowCount()):
            for column in (2, 3):
                item = self.accounts.item(row, column)
                if item:
                    item.setText(DURUM_CEVIRILERI.get(item.text(), item.text()))
        for row in range(self.jobs.rowCount()):
            for column in (3, 4):
                item = self.jobs.item(row, column)
                if item:
                    item.setText(DURUM_CEVIRILERI.get(item.text(), item.text()))
        durum = self.status.text()
        durum = durum.replace("PROFILES", "PROFİL").replace("JOBS", "İŞ").replace("DELIVERIES", "YAYIN")
        self.status.setText(durum)

    def error(self, title: str, details: str) -> None:
        super().error(HATA_BASLIKLARI.get(title, cevir(title)), cevir(details))

    def log(self, message: str) -> None:
        replacements = {
            "Added authorized profile": "Yetkilendirilmiş profil eklendi:",
            "Removed profile and its queued deployments": "Profil ve kuyruktaki yayınları kaldırıldı",
            "Completed": "Tamamlandı:",
            "compliant renditions": "standartlara uygun çıktı",
            "Queued deployment after deterministic 23-hour verification":
                "Yayın, kesin 23 saat denetiminden sonra kuyruğa eklendi",
            "Compliance guard blocked deployment": "Uyumluluk koruması yayını engelledi",
            "Removed deployment": "Yayın kaldırıldı",
            "TikTok accepted deployment": "TikTok yayını kabul etti",
            "delivery history updated": "yayın geçmişi güncellendi",
            "ERROR": "HATA",
        }
        for source, target in replacements.items():
            message = message.replace(source, target)
        super().log(cevir(message))

    def choose_master(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Ana medya dosyasını seç", "", "Medya dosyaları (*.mp4 *.mov *.mkv *.webm)"
        )
        if path:
            self.master.setText(path)
            if not self.output_dir.text():
                source = Path(path)
                self.output_dir.setText(str(source.parent / f"{source.stem}-ciktilar"))

    def choose_output(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Çıktı klasörünü seç")
        if path:
            self.output_dir.setText(path)

    def choose_queue_video(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Yayınlanacak medyayı seç", "", "MP4 video (*.mp4)"
        )
        if path:
            self.queue_video.setText(path)


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("SignalDesk Ajans Paneli")
    app.setOrganizationName("SignalDesk")
    app.setStyle("Fusion")
    QLocale.setDefault(QLocale(QLocale.Turkish, QLocale.Turkey))
    pencere = TurkceAnaPencere()
    pencere.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
