from __future__ import annotations

"""Test-first, one-proxy-per-account configuration tab."""

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (
    QComboBox, QHBoxLayout, QHeaderView, QLabel, QMessageBox, QPlainTextEdit,
    QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

import network_identity
import proxy_health


class ProxyTestWorker(QThread):
    row_result = Signal(int, object)
    completed = Signal()
    failed = Signal(str)

    def __init__(self, identities: list[network_identity.NetworkIdentity], parent=None):
        super().__init__(parent)
        self.identities = identities

    def run(self) -> None:
        try:
            for index, identity in enumerate(self.identities):
                self.row_result.emit(index, proxy_health.test(identity))
            self.completed.emit()
        except Exception as exc:
            self.failed.emit(str(exc))


def install(window_class) -> None:
    if getattr(window_class, "_network_identity_gui_installed", False):
        return
    original_build = window_class.build_ui
    original_refresh = window_class.refresh

    def account_names(self) -> list[str]:
        snapshot = self.registry.snapshot()
        return [
            str(row.get("profile_name") or row.get("name") or "").strip()
            for row in snapshot.get("accounts", [])
            if str(row.get("profile_name") or row.get("name") or "").strip()
        ]

    def network_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 18, 0, 0)
        layout.setSpacing(14)

        title = QLabel("Proxy Testi ve Hesap Eşleştirme")
        title.setObjectName("sectionTitle")
        guide = QLabel(
            "Her satıra host:port:kullanıcı:parola yazın. Önce tüm proxyler "
            "sabit çıkış IP, HTTPS erişimi ve gecikme açısından test edilir. "
            "İlk proxy ilk hesaba, ikinci proxy ikinci hesaba kalıcı atanır."
        )
        guide.setObjectName("muted")
        guide.setWordWrap(True)
        layout.addWidget(title)
        layout.addWidget(guide)

        type_row = QHBoxLayout()
        type_row.addWidget(QLabel("Proxy tipi"))
        self.proxy_scheme = QComboBox()
        self.proxy_scheme.addItems(["http", "https", "socks5"])
        self.proxy_scheme.currentTextChanged.connect(self.proxy_input_changed)
        type_row.addWidget(self.proxy_scheme)
        type_row.addStretch()
        layout.addLayout(type_row)

        self.proxy_list_input = QPlainTextEdit()
        self.proxy_list_input.setPlaceholderText(
            "31.59.20.176:6754:kullanici:parola\n"
            "31.56.127.193:7684:kullanici2:parola2"
        )
        self.proxy_list_input.setMinimumHeight(150)
        self.proxy_list_input.textChanged.connect(self.proxy_input_changed)
        layout.addWidget(self.proxy_list_input)

        actions = QHBoxLayout()
        self.proxy_test_button = QPushButton("1. PROXYLERİ TEST ET")
        self.proxy_test_button.clicked.connect(self.test_proxy_list)
        self.proxy_assign_button = QPushButton("2. TESTİ GEÇENLERİ SIRAYLA ATA")
        self.proxy_assign_button.setObjectName("primaryButton")
        self.proxy_assign_button.setEnabled(False)
        self.proxy_assign_button.clicked.connect(self.assign_proxy_list)
        clear = QPushButton("Atamaları kaldır")
        clear.setObjectName("quietButton")
        clear.clicked.connect(self.clear_all_proxy_assignments)
        actions.addWidget(self.proxy_test_button)
        actions.addWidget(self.proxy_assign_button)
        actions.addWidget(clear)
        actions.addStretch()
        layout.addLayout(actions)

        self.proxy_mapping = QTableWidget(0, 6)
        self.proxy_mapping.setHorizontalHeaderLabels(
            ["Sıra", "Hesap", "Proxy", "Test", "Çıkış IP", "Ülke / Gecikme"]
        )
        header = self.proxy_mapping.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.Stretch)
        layout.addWidget(self.proxy_mapping, 1)

        self.proxy_status = QLabel("Listeyi girin, sonra proxyleri test edin.")
        self.proxy_status.setObjectName("muted")
        self.proxy_status.setWordWrap(True)
        layout.addWidget(self.proxy_status)

        self._tested_identities: list[network_identity.NetworkIdentity] = []
        self._test_results: dict[int, proxy_health.ProxyHealth] = {}
        self._tested_source = ""
        self.proxy_test_worker = None
        return page

    def proxy_source(self) -> str:
        return f"{self.proxy_scheme.currentText()}\n{self.proxy_list_input.toPlainText().strip()}"

    def proxy_input_changed(self, *_args) -> None:
        if not hasattr(self, "proxy_assign_button"):
            return
        if self._tested_source and self.proxy_source() != self._tested_source:
            self.proxy_assign_button.setEnabled(False)
            self.proxy_status.setText("Liste değişti. Atamadan önce yeniden test edin.")

    def refresh_proxy_mapping(self) -> None:
        profiles = self.account_names()
        tested = getattr(self, "_tested_identities", [])
        rows = max(len(profiles), len(tested))
        self.proxy_mapping.setRowCount(rows)
        for row in range(rows):
            profile = profiles[row] if row < len(profiles) else ""
            saved = network_identity.load(profile) if profile else network_identity.NetworkIdentity()
            identity = tested[row] if row < len(tested) else saved
            result = self._test_results.get(row)
            if result is None and identity.server:
                result = proxy_health.latest(identity)
            state = "GEÇTİ" if result and result.ok else "BAŞARISIZ" if result else "Test yok"
            values = [
                str(row + 1),
                profile or "Hesap yok",
                identity.server or "Doğrudan bağlantı",
                state,
                result.exit_ip if result else "",
                f"{result.country_code or '-'} / {result.median_latency_ms} ms" if result else "",
            ]
            for column, value in enumerate(values):
                self.proxy_mapping.setItem(row, column, QTableWidgetItem(value))

    def handle_proxy_result(self, index: int, result: proxy_health.ProxyHealth) -> None:
        self._test_results[index] = result
        self.refresh_proxy_mapping()
        completed = len(self._test_results)
        self.proxy_status.setText(
            f"Test sürüyor: {completed}/{len(self._tested_identities)} tamamlandı"
        )

    def test_proxy_list(self) -> None:
        if self.proxy_test_worker and self.proxy_test_worker.isRunning():
            return
        try:
            identities = network_identity.parse_proxy_list(
                self.proxy_list_input.toPlainText(), self.proxy_scheme.currentText()
            )
            self._tested_identities = identities
            self._test_results = {}
            self._tested_source = self.proxy_source()
            self.proxy_test_button.setEnabled(False)
            self.proxy_assign_button.setEnabled(False)
            self.proxy_status.setText(
                "Proxyler HTTPS erişimi, sabit çıkış IP ve gecikme açısından test ediliyor..."
            )
            self.refresh_proxy_mapping()
            worker = ProxyTestWorker(identities, self)
            self.proxy_test_worker = worker
            worker.row_result.connect(self.handle_proxy_result)
            worker.completed.connect(self.proxy_test_finished)
            worker.failed.connect(self.proxy_test_failed)
            worker.start()
        except Exception as exc:
            QMessageBox.critical(self, "Proxy test hatası", str(exc))

    def proxy_test_finished(self) -> None:
        self.proxy_test_button.setEnabled(True)
        profiles = self.account_names()
        required = min(len(profiles), len(self._tested_identities))
        passed_required = required == len(profiles) and all(
            self._test_results.get(index) and self._test_results[index].ok
            for index in range(required)
        )
        passed_total = sum(1 for result in self._test_results.values() if result.ok)
        self.proxy_assign_button.setEnabled(bool(profiles) and passed_required)
        self.proxy_status.setText(
            f"Test bitti: {passed_total}/{len(self._tested_identities)} proxy aktif. "
            + ("Atamaya hazır." if passed_required else "Her hesap için sırasındaki proxy testi geçmeli.")
        )
        self.refresh_proxy_mapping()

    def proxy_test_failed(self, detail: str) -> None:
        self.proxy_test_button.setEnabled(True)
        self.proxy_assign_button.setEnabled(False)
        self.proxy_status.setText("Proxy testi tamamlanamadı.")
        QMessageBox.critical(self, "Proxy test hatası", detail)

    def assign_proxy_list(self) -> None:
        try:
            if self.proxy_source() != self._tested_source:
                raise RuntimeError("Liste testten sonra değişti. Yeniden test edin.")
            profiles = self.account_names()
            if not profiles:
                raise RuntimeError("Önce en az bir hesap ekleyin.")
            if len(self._tested_identities) < len(profiles):
                raise RuntimeError(
                    f"{len(profiles)} hesap için en az {len(profiles)} proxy gerekli."
                )
            for index in range(len(profiles)):
                result = self._test_results.get(index)
                if not result or not result.ok:
                    raise RuntimeError(f"{index + 1}. proxy aktif değil veya testi geçmedi.")
            assignments = network_identity.assign_in_order(profiles, self._tested_identities)
            self.refresh_proxy_mapping()
            self.proxy_status.setText(
                f"{len(assignments)} hesap sırayla sabit proxyye bağlandı. "
                "Yayınlar bu eşleştirmeyi kullanacak."
            )
            QMessageBox.information(
                self,
                "Proxy ataması tamamlandı",
                f"{len(assignments)} hesap için test edilmiş proxy atandı.",
            )
        except Exception as exc:
            QMessageBox.critical(self, "Proxy atama hatası", str(exc))

    def clear_all_proxy_assignments(self) -> None:
        for profile in self.account_names():
            network_identity.delete(profile)
        self._tested_identities = []
        self._test_results = {}
        self._tested_source = ""
        self.proxy_assign_button.setEnabled(False)
        self.refresh_proxy_mapping()
        self.proxy_status.setText("Tüm hesaplar doğrudan bağlantıya döndürüldü.")

    def build_ui(self) -> None:
        original_build(self)
        self.network_identity_page = self.network_tab()
        self.tabs.addTab(self.network_identity_page, "Proxy Listesi")
        self.refresh_proxy_mapping()

    def refresh(self) -> None:
        original_refresh(self)
        if hasattr(self, "proxy_mapping"):
            self.refresh_proxy_mapping()

    methods = {
        "build_ui": build_ui,
        "refresh": refresh,
        "account_names": account_names,
        "network_tab": network_tab,
        "proxy_source": proxy_source,
        "proxy_input_changed": proxy_input_changed,
        "refresh_proxy_mapping": refresh_proxy_mapping,
        "handle_proxy_result": handle_proxy_result,
        "test_proxy_list": test_proxy_list,
        "proxy_test_finished": proxy_test_finished,
        "proxy_test_failed": proxy_test_failed,
        "assign_proxy_list": assign_proxy_list,
        "clear_all_proxy_assignments": clear_all_proxy_assignments,
    }
    for name, value in methods.items():
        setattr(window_class, name, value)
    window_class._network_identity_gui_installed = True
