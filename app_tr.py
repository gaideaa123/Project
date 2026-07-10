from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import keyring
from PySide6.QtCore import QLocale
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QFileDialog, QFormLayout, QFrame, QHBoxLayout,
    QLabel, QLineEdit, QMessageBox, QPushButton, QTableWidgetItem,
    QVBoxLayout, QWidget,
)

import app as core

AYAR_SERVISI = "signaldesk-agency-console.app-settings"
VARSAYILAN_REDIRECT = "http://127.0.0.1:3455/callback/"
VARSAYILAN_KAPSAMLAR = "user.info.basic,video.publish"

METINLER = {
    "SIGNALDESK / AGENCY OPERATIONS": "SIGNALDESK / AJANS OPERASYONLARI",
    "Ship content with a paper trail.": "İçeriği kayıtlı, kontrollü ve güvenli yayınla.",
    "Profile Manager": "Profil Yönetimi",
    "Batch Processing": "Toplu Medya İşleme",
    "Deployment Queue": "Yayın Kuyruğu",
    "Connect an official channel": "Resmî bir kanal bağla",
    "OAuth tokens stay in the operating system keychain. JSON never contains credentials.":
        "OAuth belirteçleri işletim sisteminin güvenli kasasında tutulur. JSON dosyasına kimlik bilgisi yazılmaz.",
    "Profile": "Profil", "Platform": "Platform", "Access token": "Erişim belirteci",
    "Refresh token": "Yenileme belirteci", "Network gateway": "Ağ geçidi",
    "Add profile": "Profil ekle", "Authorized profiles": "Yetkilendirilmiş profiller",
    "Remove selected": "Seçileni kaldır", "Token": "Belirteç", "Network": "Ağ",
    "Added": "Eklenme", "H.264 rendition batch": "H.264 çıktı paketi",
    "CRF 20 to 23, normalized H.264/AAC, mobile sharpening, optional micro-grain, and loudness normalization.":
        "CRF 20-23, standart H.264/AAC, mobil keskinlik, hafif film dokusu ve ses normalizasyonu.",
    "Select master": "Ana dosyayı seç", "Select folder": "Çıktı klasörünü seç",
    "Start batch": "Toplu işlemi başlat", "Processing log": "İşlem günlüğü",
    "Browse": "Gözat", "Deployment time": "Yayın zamanı", "Caption": "Açıklama",
    "Repeat daily": "Her gün tekrarla", "Queue deployment": "Yayını kuyruğa ekle",
    "23-hour guarded pipeline": "23 saat korumalı yayın hattı",
    "Run due jobs": "Zamanı gelenleri çalıştır", "Asset": "Medya",
    "Next run": "Sonraki çalışma", "Cadence": "Tekrar", "State": "Durum",
    "Publish ID": "Yayın kimliği",
}

YER_TUTUCULAR = {
    "Brand Europe": "Marka Türkiye",
    "Official OAuth access token": "Resmî OAuth erişim belirteci",
    "Official OAuth refresh token": "Resmî OAuth yenileme belirteci",
    "Optional approved corporate gateway": "İsteğe bağlı kurumsal ağ geçidi",
    "Master media file": "Ana medya dosyası", "Output folder": "Çıktı klasörü",
    "Compliant MP4 rendition": "Standartlara uygun MP4 çıktısı",
    "Approved caption": "Onaylanmış gönderi açıklaması",
}

DURUM = {
    "Ready": "Hazır", "Refresh soon": "Yakında yenilenecek", "Gateway": "Ağ geçidi",
    "Direct": "Doğrudan", "Daily": "Günlük", "Once": "Tek sefer",
    "Queued": "Kuyrukta", "Running": "Çalışıyor", "Failed": "Başarısız",
    "Submitted": "Gönderildi",
}

HATA = {
    "Missing details": "Eksik bilgi", "Could not add profile": "Profil eklenemedi",
    "Nothing selected": "Seçim yapılmadı", "Missing paths": "Dosya yolları eksik",
    "Batch failed": "Toplu işlem başarısız", "Incomplete deployment": "Yayın bilgileri eksik",
    "Could not queue deployment": "Yayın kuyruğa eklenemedi",
    "Deployment is active": "Yayın işlemi sürüyor", "Deployment failed": "Yayın başarısız",
}

PARCALAR = {
    "Profile name, access token, and refresh token are required":
        "Profil adı, erişim belirteci ve yenileme belirteci zorunludur",
    "Select a profile first": "Önce bir profil seçin",
    "Choose an existing master file and output folder":
        "Var olan bir ana medya dosyası ve çıktı klasörü seçin",
    "Choose a profile, an existing MP4, and a caption":
        "Bir profil, var olan bir MP4 dosyası ve açıklama seçin",
    "Select a deployment first": "Önce bir yayın seçin",
    "Wait for the current network request to finish": "Etkin ağ işleminin bitmesini bekleyin",
    "Profile names must be unique": "Profil adları benzersiz olmalıdır",
    "No access token is stored for this profile": "Bu profil için erişim belirteci kayıtlı değil",
    "Set TIKTOK_CLIENT_KEY and TIKTOK_CLIENT_SECRET for refresh":
        "API Ayarları sekmesinden Client Key ve Client Secret değerlerini kaydedin",
    "23-hour guard": "23 saat koruması",
}


def cevir(metin: str) -> str:
    sonuc = METINLER.get(metin, metin)
    for kaynak, hedef in PARCALAR.items():
        sonuc = sonuc.replace(kaynak, hedef)
    return sonuc


def kasa_oku(ad: str, varsayilan: str = "") -> str:
    try:
        return keyring.get_password(AYAR_SERVISI, ad) or varsayilan
    except Exception:
        return varsayilan


def kayitli_ayarlari_ortama_yukle() -> None:
    esleme = {
        "TIKTOK_CLIENT_KEY": "client_key",
        "TIKTOK_CLIENT_SECRET": "client_secret",
        "TIKTOK_REDIRECT_URI": "redirect_uri",
        "TIKTOK_SCOPES": "scopes",
    }
    varsayilanlar = {"redirect_uri": VARSAYILAN_REDIRECT, "scopes": VARSAYILAN_KAPSAMLAR}
    for ortam_adi, kasa_adi in esleme.items():
        deger = kasa_oku(kasa_adi, varsayilanlar.get(kasa_adi, ""))
        if deger:
            os.environ[ortam_adi] = deger


class TurkceAnaPencere(core.MainWindow):
    def build_ui(self) -> None:
        super().build_ui()
        self.setWindowTitle("SignalDesk Ajans Paneli")
        self.tabs.addTab(self.api_ayarlari_sekmesi(), "API Ayarları")
        self._arayuzu_cevir()

    def api_ayarlari_sekmesi(self) -> QWidget:
        sayfa = QWidget()
        dis = QHBoxLayout(sayfa)
        dis.setContentsMargins(0, 18, 0, 0)

        panel = QFrame()
        panel.setObjectName("panel")
        yerlesim = QVBoxLayout(panel)
        yerlesim.setContentsMargins(28, 24, 28, 28)
        yerlesim.setSpacing(16)

        baslik = QLabel("TikTok API ve OAuth Ayarları")
        baslik.setObjectName("sectionTitle")
        aciklama = QLabel(
            "Client Key ve Client Secret uygulamaya aittir. Access Token ve Refresh Token ise "
            "her TikTok profiline özeldir ve Profil Yönetimi sekmesinden girilir. Tüm gizli "
            "değerler Windows Kimlik Bilgisi Yöneticisi'nde saklanır."
        )
        aciklama.setObjectName("muted")
        aciklama.setWordWrap(True)
        yerlesim.addWidget(baslik)
        yerlesim.addWidget(aciklama)

        form = QFormLayout()
        form.setSpacing(12)
        self.client_key_alani = QLineEdit(kasa_oku("client_key"))
        self.client_key_alani.setPlaceholderText("TikTok Developer Portal > Manage apps > Client key")
        self.client_secret_alani = QLineEdit(kasa_oku("client_secret"))
        self.client_secret_alani.setEchoMode(QLineEdit.Password)
        self.client_secret_alani.setPlaceholderText("TikTok Developer Portal > Manage apps > Client secret")
        self.redirect_alani = QLineEdit(kasa_oku("redirect_uri", VARSAYILAN_REDIRECT))
        self.kapsam_alani = QLineEdit(kasa_oku("scopes", VARSAYILAN_KAPSAMLAR))
        form.addRow("Client Key", self.client_key_alani)
        form.addRow("Client Secret", self.client_secret_alani)
        form.addRow("Redirect URI", self.redirect_alani)
        form.addRow("OAuth kapsamları", self.kapsam_alani)
        yerlesim.addLayout(form)

        dugmeler = QHBoxLayout()
        kaydet = QPushButton("Ayarları güvenli kasaya kaydet")
        kaydet.setObjectName("primaryButton")
        kaydet.clicked.connect(self.api_ayarlari_kaydet)
        yetkilendir = QPushButton("Profil belirteçlerini al")
        yetkilendir.clicked.connect(self.oauth_yardimcisini_ac)
        secret_goster = QCheckBox("Client Secret'ı göster")
        secret_goster.toggled.connect(
            lambda acik: self.client_secret_alani.setEchoMode(
                QLineEdit.Normal if acik else QLineEdit.Password
            )
        )
        dugmeler.addWidget(kaydet)
        dugmeler.addWidget(yetkilendir)
        dugmeler.addWidget(secret_goster)
        dugmeler.addStretch()
        yerlesim.addLayout(dugmeler)

        adimlar = QLabel(
            "1. developers.tiktok.com > Manage apps bölümünde uygulamanı aç.\n"
            "2. Login Kit ve Content Posting API ürünlerini ekle.\n"
            "3. Redirect URI olarak http://127.0.0.1:3455/callback/ değerini kaydet.\n"
            "4. Client Key ve Client Secret değerlerini yukarıya yapıştırıp kaydet.\n"
            "5. Profil belirteçlerini al düğmesine bas, tarayıcıda doğru TikTok hesabına izin ver.\n"
            "6. Terminalde çıkan Access Token ve Refresh Token değerlerini Profil Yönetimi'ne gir."
        )
        adimlar.setObjectName("muted")
        adimlar.setWordWrap(True)
        yerlesim.addWidget(adimlar)
        yerlesim.addStretch()
        dis.addWidget(panel, 1)
        return sayfa

    def api_ayarlari_kaydet(self) -> None:
        client_key = self.client_key_alani.text().strip()
        client_secret = self.client_secret_alani.text().strip()
        redirect_uri = self.redirect_alani.text().strip()
        scopes = self.kapsam_alani.text().strip()
        if not client_key or not client_secret or not redirect_uri or not scopes:
            QMessageBox.warning(self, "Eksik API ayarı", "Dört alanın tamamını doldurun.")
            return
        if not redirect_uri.startswith(("http://127.0.0.1:", "http://localhost:")):
            QMessageBox.warning(
                self, "Redirect URI geçersiz",
                "Masaüstü yardımcı akışı için port içeren 127.0.0.1 veya localhost adresi kullanın.",
            )
            return
        try:
            for ad, deger in {
                "client_key": client_key, "client_secret": client_secret,
                "redirect_uri": redirect_uri, "scopes": scopes,
            }.items():
                keyring.set_password(AYAR_SERVISI, ad, deger)
            kayitli_ayarlari_ortama_yukle()
            self.log("API ayarları güvenli kasaya kaydedildi")
            QMessageBox.information(
                self, "Kaydedildi",
                "API ayarları güvenli kasaya kaydedildi ve bu oturumda etkinleştirildi.",
            )
        except Exception as exc:
            self.error("API ayarları kaydedilemedi", str(exc))

    def oauth_yardimcisini_ac(self) -> None:
        self.api_ayarlari_kaydet()
        if not os.getenv("TIKTOK_CLIENT_KEY") or not os.getenv("TIKTOK_CLIENT_SECRET"):
            return
        yardimci = Path(__file__).with_name("oauth_helper.py")
        if not yardimci.is_file():
            self.error("OAuth yardımcısı bulunamadı", str(yardimci))
            return
        try:
            if sys.platform == "win32":
                subprocess.Popen(
                    [sys.executable, str(yardimci)], cwd=str(yardimci.parent),
                    env=os.environ.copy(), creationflags=subprocess.CREATE_NEW_CONSOLE,
                )
            else:
                subprocess.Popen(
                    [sys.executable, str(yardimci)], cwd=str(yardimci.parent),
                    env=os.environ.copy(),
                )
            self.log("OAuth yardımcısı açıldı; tarayıcıdaki TikTok izin adımlarını tamamlayın")
        except Exception as exc:
            self.error("OAuth yardımcısı açılamadı", str(exc))

    def _arayuzu_cevir(self) -> None:
        if hasattr(self, "tabs"):
            adlar = ["Profil Yönetimi", "Toplu Medya İşleme", "Yayın Kuyruğu", "API Ayarları"]
            for index, ad in enumerate(adlar):
                if index < self.tabs.count():
                    self.tabs.setTabText(index, ad)
        for etiket in self.findChildren(QLabel):
            etiket.setText(METINLER.get(etiket.text(), etiket.text()))
        for dugme in self.findChildren(QPushButton):
            dugme.setText(METINLER.get(dugme.text(), dugme.text()))
        for kutu in self.findChildren(QCheckBox):
            kutu.setText(METINLER.get(kutu.text(), kutu.text()))
        for alan in self.findChildren(QLineEdit):
            alan.setPlaceholderText(YER_TUTUCULAR.get(alan.placeholderText(), alan.placeholderText()))

        if hasattr(self, "accounts"):
            self.accounts.setHorizontalHeaderLabels(["Profil", "Platform", "Belirteç", "Ağ", "Eklenme"])
        if hasattr(self, "jobs"):
            self.jobs.setHorizontalHeaderLabels(
                ["Profil", "Medya", "Sonraki çalışma", "Tekrar", "Durum", "Yayın kimliği"]
            )
        # Eski veya farklı app.py sürümlerinde bu alanlar olmayabilir. Arayüz artık çökmez.
        if hasattr(self, "batch_size"):
            self.batch_size.setSuffix(" çıktı")
        if hasattr(self, "run_at"):
            self.run_at.setDisplayFormat("dd.MM.yyyy HH:mm")

    def refresh(self) -> None:
        super().refresh()
        self._arayuzu_cevir()
        if hasattr(self, "accounts"):
            for row in range(self.accounts.rowCount()):
                for column in (2, 3):
                    item = self.accounts.item(row, column)
                    if item:
                        item.setText(DURUM.get(item.text(), item.text()))
        if hasattr(self, "jobs"):
            for row in range(self.jobs.rowCount()):
                for column in (3, 4):
                    item = self.jobs.item(row, column)
                    if item:
                        item.setText(DURUM.get(item.text(), item.text()))
        if hasattr(self, "status"):
            metin = self.status.text()
            metin = metin.replace("PROFILES", "PROFİL").replace("JOBS", "İŞ").replace("DELIVERIES", "YAYIN")
            self.status.setText(metin)

    def error(self, title: str, details: str) -> None:
        super().error(HATA.get(title, cevir(title)), cevir(details))

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
    kayitli_ayarlari_ortama_yukle()
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
