from __future__ import annotations

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import QComboBox,QHBoxLayout,QLabel,QMessageBox,QPlainTextEdit,QPushButton,QSpinBox,QTableWidget,QTableWidgetItem,QVBoxLayout,QWidget

import network_identity, proxy_health, publication_pacing


class ProxyTestWorker(QThread):
    row_result=Signal(int,object); completed=Signal(); failed=Signal(str)
    def __init__(self,identities,parent=None): super().__init__(parent); self.identities=identities
    def run(self):
        try:
            for index,identity in enumerate(self.identities): self.row_result.emit(index,proxy_health.test(identity))
            self.completed.emit()
        except Exception as exc: self.failed.emit(str(exc))


def install(window_class):
    if getattr(window_class,"_network_identity_gui_installed",False): return
    original_build=window_class.build_ui; original_refresh=window_class.refresh
    def network_tab(self):
        page=QWidget(); layout=QVBoxLayout(page); title=QLabel("Proxy Test ve Sabit Hesap Ağı"); title.setStyleSheet("font-size:20px;font-weight:700"); layout.addWidget(title)
        guide=QLabel("Listeyi host:port:kullanıcı:parola biçiminde yapıştırın. Önce test edin; yalnız HTTPS, sabit çıkış IP ve kabul edilebilir gecikme sağlayan proxyler atanabilir. İlk proxy ilk hesaba kalıcı kilitlenir."); guide.setWordWrap(True); layout.addWidget(guide)
        row=QHBoxLayout(); row.addWidget(QLabel("Tip")); self.proxy_scheme=QComboBox(); self.proxy_scheme.addItems(["http","https","socks5"]); row.addWidget(self.proxy_scheme); row.addWidget(QLabel("Hesaplar arası bekleme")); self.pacing_seconds=QSpinBox(); self.pacing_seconds.setRange(30,900); self.pacing_seconds.setValue(publication_pacing.get_seconds()); self.pacing_seconds.setSuffix(" sn"); row.addWidget(self.pacing_seconds); row.addStretch(); layout.addLayout(row)
        self.proxy_list_input=QPlainTextEdit(); self.proxy_list_input.setPlaceholderText("host:port:kullanıcı:parola"); layout.addWidget(self.proxy_list_input)
        actions=QHBoxLayout(); self.proxy_test_button=QPushButton("PROXY TEST"); self.proxy_test_button.clicked.connect(self.test_proxy_list); assign=QPushButton("TESTİ GEÇEN PROXYLERİ HESAPLARA ATA"); assign.clicked.connect(self.assign_proxy_list); clear=QPushButton("Atamaları kaldır"); clear.clicked.connect(self.clear_all_proxy_assignments); [actions.addWidget(x) for x in (self.proxy_test_button,assign,clear)]; actions.addStretch(); layout.addLayout(actions)
        self.proxy_mapping=QTableWidget(0,6); self.proxy_mapping.setHorizontalHeaderLabels(["Sıra","Hesap","Proxy","Test","Çıkış IP","Ülke / Gecikme"]); self.proxy_mapping.horizontalHeader().setStretchLastSection(True); layout.addWidget(self.proxy_mapping); self.proxy_status=QLabel("Önce proxyleri test edin"); layout.addWidget(self.proxy_status); self._tested_identities=[]; self._test_results={}; self.proxy_test_worker=None; return page
    def refresh_proxy_mapping(self):
        profiles=self.account_names() if hasattr(self,"account_names") else []; rows=max(len(profiles),len(getattr(self,"_tested_identities",[]))); self.proxy_mapping.setRowCount(rows)
        for row in range(rows):
            profile=profiles[row] if row<len(profiles) else ""; identity=network_identity.load(profile) if profile else (self._tested_identities[row] if row<len(self._tested_identities) else network_identity.NetworkIdentity()); result=self._test_results.get(row)
            values=[str(row+1),profile,identity.server or "Doğrudan",("GEÇTİ" if result and result.ok else "BAŞARISIZ" if result else "Test yok"),result.exit_ip if result else "",f"{result.country_code} / {result.median_latency_ms} ms" if result else ""]
            for col,value in enumerate(values): self.proxy_mapping.setItem(row,col,QTableWidgetItem(value))
    def test_proxy_list(self):
        try:
            self._tested_identities=network_identity.parse_proxy_list(self.proxy_list_input.toPlainText(),self.proxy_scheme.currentText()); self._test_results={}; self.proxy_test_button.setEnabled(False); self.proxy_status.setText("Proxyler HTTPS, çıkış IP, sabitlik ve gecikme açısından test ediliyor..."); refresh_proxy_mapping(self); worker=ProxyTestWorker(self._tested_identities,self); self.proxy_test_worker=worker; worker.row_result.connect(lambda i,r:(self._test_results.__setitem__(i,r),refresh_proxy_mapping(self))); worker.completed.connect(self.proxy_test_finished); worker.failed.connect(self.proxy_test_failed); worker.start()
        except Exception as exc: QMessageBox.critical(self,"Proxy test hatası",str(exc))
    def proxy_test_finished(self):
        self.proxy_test_button.setEnabled(True); passed=sum(1 for r in self._test_results.values() if r.ok); self.proxy_status.setText(f"Test bitti: {passed}/{len(self._tested_identities)} proxy geçti"); refresh_proxy_mapping(self)
    def proxy_test_failed(self,detail): self.proxy_test_button.setEnabled(True); QMessageBox.critical(self,"Proxy test hatası",detail)
    def assign_proxy_list(self):
        try:
            profiles=self.account_names(); identities=self._tested_identities
            if len(self._test_results)!=len(identities) or any(not r.ok for r in self._test_results.values()): raise RuntimeError("Tüm proxyler testi geçmeden atama yapılamaz")
            publication_pacing.set_seconds(self.pacing_seconds.value()); assignments=network_identity.assign_in_order(profiles,identities); refresh_proxy_mapping(self); self.proxy_status.setText(f"{len(assignments)} hesap kilitlendi; bekleme {publication_pacing.get_seconds()} sn"); self.proxy_list_input.clear()
        except Exception as exc: QMessageBox.critical(self,"Proxy atama hatası",str(exc))
    def clear_all_proxy_assignments(self):
        for profile in self.account_names(): network_identity.delete(profile)
        refresh_proxy_mapping(self); self.proxy_status.setText("Tüm profil-proxy kilitleri kaldırıldı")
    def build_ui(self): original_build(self); self.network_identity_page=network_tab(self); self.tabs.addTab(self.network_identity_page,"Proxy Test"); refresh_proxy_mapping(self)
    def refresh(self): original_refresh(self); refresh_proxy_mapping(self) if hasattr(self,"proxy_mapping") else None
    for name,value in {"build_ui":build_ui,"refresh":refresh,"network_tab":network_tab,"refresh_proxy_mapping":refresh_proxy_mapping,"test_proxy_list":test_proxy_list,"proxy_test_finished":proxy_test_finished,"proxy_test_failed":proxy_test_failed,"assign_proxy_list":assign_proxy_list,"clear_all_proxy_assignments":clear_all_proxy_assignments}.items(): setattr(window_class,name,value)
    window_class._network_identity_gui_installed=True
