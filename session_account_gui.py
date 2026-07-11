from __future__ import annotations

"""Session ID account management added without replacing existing app_tr tabs."""

import inspect
from typing import Any

from PySide6.QtWidgets import (
    QCheckBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout, QLabel,
    QLineEdit, QMessageBox, QPushButton, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget,
)

import tiktok_login

try:
    import web_uploader
    if hasattr(tiktok_login, "install"):
        tiktok_login.install(web_uploader)
except Exception:
    # Account/session management remains available even if Playwright is not
    # installed yet. Runtime upload errors retain their own diagnostics.
    pass


def account_rows(window: Any) -> list[dict[str, Any]]:
    state = window.registry.snapshot()
    rows = state.get("accounts", [])
    return rows if isinstance(rows, list) else []


def account_name(account: dict[str, Any]) -> str:
    return str(account.get("name") or account.get("profile_name") or "").strip()


def add_registry_account(window: Any, name: str) -> dict[str, Any]:
    method = window.registry.add_account
    parameter_count = len(inspect.signature(method).parameters)
    if parameter_count >= 2:
        return method(name, "TikTok")
    return method(name)


def delete_registry_account(window: Any, account_id: str) -> None:
    if account_id:
        window.registry.delete_account(account_id)


def session_page(window: Any) -> QWidget:
    page = QWidget()
    layout = QVBoxLayout(page)
    layout.setContentsMargins(0, 18, 0, 0)
    layout.setSpacing(14)

    title = QLabel("Session ID ile TikTok Hesapları")
    title.setObjectName("sectionTitle")
    note = QLabel(
        "Profil adı ve sessionid girin. Session ID yalnız işletim sistemi "
        "güvenli kasasında tutulur; tabloda veya proje dosyalarında gösterilmez."
    )
    note.setObjectName("muted")
    note.setWordWrap(True)
    layout.addWidget(title)
    layout.addWidget(note)

    actions = QHBoxLayout()
    window.session_add_button = QPushButton("SESSION ID İLE YENİ HESAP EKLE")
    window.session_add_button.setObjectName("primaryButton")
    window.session_add_button.clicked.connect(lambda: add_session_account(window))
    refresh_button = QPushButton("Listeyi yenile")
    refresh_button.setObjectName("quietButton")
    refresh_button.clicked.connect(lambda: refresh_session_accounts(window))
    actions.addWidget(window.session_add_button)
    actions.addWidget(refresh_button)
    actions.addStretch()
    layout.addLayout(actions)

    window.session_accounts_table = QTableWidget(0, 4)
    window.session_accounts_table.setHorizontalHeaderLabels(
        ["Sıra", "Profil", "Session ID", "İşlem"]
    )
    window.session_accounts_table.horizontalHeader().setStretchLastSection(True)
    layout.addWidget(window.session_accounts_table, 1)

    window.session_status = QLabel("Hazır")
    window.session_status.setObjectName("muted")
    layout.addWidget(window.session_status)
    return page


def session_dialog(parent: Any, title: str, profile: str = "") -> tuple[bool, str, str]:
    dialog = QDialog(parent)
    dialog.setWindowTitle(title)
    form = QFormLayout(dialog)
    profile_input = QLineEdit(profile)
    profile_input.setPlaceholderText("TikTok profil adı")
    profile_input.setReadOnly(bool(profile))
    session_input = QLineEdit()
    session_input.setPlaceholderText("sessionid veya sessionid=...;")
    session_input.setEchoMode(QLineEdit.Password)
    show = QCheckBox("Session ID'yi göster")
    show.toggled.connect(
        lambda checked: session_input.setEchoMode(
            QLineEdit.Normal if checked else QLineEdit.Password
        )
    )
    form.addRow("Profil adı", profile_input)
    form.addRow("Session ID", session_input)
    form.addRow("", show)
    buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
    buttons.accepted.connect(dialog.accept)
    buttons.rejected.connect(dialog.reject)
    form.addRow(buttons)
    accepted = dialog.exec() == QDialog.Accepted
    return accepted, profile_input.text().strip(), session_input.text()


def add_session_account(window: Any) -> None:
    accepted, name, raw_session = session_dialog(
        window, "Session ID ile yeni TikTok hesabı"
    )
    if not accepted:
        return
    account: dict[str, Any] | None = None
    try:
        if not name:
            raise RuntimeError("Profil adı boş olamaz")
        tiktok_login._session_value(raw_session)
        account = add_registry_account(window, name)
        try:
            tiktok_login.save_session(name, raw_session)
        except Exception:
            delete_registry_account(window, str(account.get("id") or ""))
            raise
        if hasattr(window, "refresh"):
            window.refresh()
        refresh_session_accounts(window)
        window.session_status.setText(f"{name} Session ID ile eklendi")
        QMessageBox.information(window, "Hesap eklendi", f"{name} güvenli şekilde eklendi.")
    except Exception as exc:
        QMessageBox.critical(window, "Hesap eklenemedi", str(exc))


def edit_session(window: Any, profile: str) -> None:
    accepted, _, raw_session = session_dialog(
        window, f"{profile}: Session ID güncelle", profile
    )
    if not accepted:
        return
    try:
        tiktok_login.save_session(profile, raw_session)
        refresh_session_accounts(window)
        window.session_status.setText(f"{profile} Session ID güncellendi")
    except Exception as exc:
        QMessageBox.critical(window, "Session ID güncellenemedi", str(exc))


def remove_session(window: Any, profile: str) -> None:
    answer = QMessageBox.question(
        window,
        "Session ID'yi kaldır",
        f"{profile} için kayıtlı Session ID güvenli kasadan silinsin mi?",
        QMessageBox.Yes | QMessageBox.No,
        QMessageBox.No,
    )
    if answer != QMessageBox.Yes:
        return
    tiktok_login.delete_session(profile)
    refresh_session_accounts(window)
    window.session_status.setText(f"{profile} Session ID kaldırıldı")


def refresh_session_accounts(window: Any) -> None:
    if not hasattr(window, "session_accounts_table"):
        return
    rows = account_rows(window)
    window.session_accounts_table.clearContents()
    window.session_accounts_table.setRowCount(len(rows))
    for row, account in enumerate(rows):
        profile = account_name(account)
        window.session_accounts_table.setItem(row, 0, QTableWidgetItem(str(row + 1)))
        window.session_accounts_table.setItem(row, 1, QTableWidgetItem(profile))
        state = "Kayıtlı" if tiktok_login.has_session(profile) else "Eksik"
        window.session_accounts_table.setItem(row, 2, QTableWidgetItem(state))
        controls = QWidget()
        control_layout = QHBoxLayout(controls)
        control_layout.setContentsMargins(0, 0, 0, 0)
        edit = QPushButton("Güncelle" if state == "Kayıtlı" else "Session ekle")
        edit.clicked.connect(lambda _=False, name=profile: edit_session(window, name))
        remove = QPushButton("Session sil")
        remove.setObjectName("quietButton")
        remove.setEnabled(state == "Kayıtlı")
        remove.clicked.connect(lambda _=False, name=profile: remove_session(window, name))
        control_layout.addWidget(edit)
        control_layout.addWidget(remove)
        control_layout.addStretch()
        window.session_accounts_table.setCellWidget(row, 3, controls)


def install(window: Any) -> None:
    if getattr(window, "_session_account_gui_installed", False):
        return
    window.session_accounts_page = session_page(window)
    window.tabs.insertTab(1, window.session_accounts_page, "Session ID Hesapları")
    window._session_account_gui_installed = True
    refresh_session_accounts(window)
