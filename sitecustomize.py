"""Installs the Web Yayını panel into app_tr.py windows.

The installer waits for the real application window, then adds one native Qt
tab. It does not alter browser security, login, CAPTCHA, 2FA, or TikTok APIs.
"""
from __future__ import annotations

try:
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication

    _original_exec = QApplication.exec

    def _exec_with_web_panel(self):
        from web_gui_integration import install_web_publish_tab

        timer = QTimer(self)
        timer.setInterval(250)

        def scan() -> None:
            for window in self.topLevelWidgets():
                if window.__class__.__name__ in {"TurkceAnaPencere", "SignalDeskTurkce"}:
                    install_web_publish_tab(window)

        timer.timeout.connect(scan)
        timer.start()
        scan()
        self._signaldesk_web_timer = timer
        return _original_exec()

    QApplication.exec = _exec_with_web_panel
except Exception:
    pass
