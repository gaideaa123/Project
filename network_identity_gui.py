from __future__ import annotations

from PySide6.QtCore import QThread,Signal
from PySide6.QtWidgets import QCheckBox,QComboBox,QHBoxLayout,QLabel,QMessageBox,QPlainTextEdit,QPushButton,QSpinBox,QTableWidget,QTableWidgetItem,QVBoxLayout,QWidget
import ab_diagnostics,network_identity,profile_integrity,proxy_health,publication_pacing
class ProxyTestWorker(QThread):
    row_result=Signal(int,object);completed=Signal();failed=Signal(str)
    def __init__(self,rows,parent=None):super().__init__(parent);self.rows=rows
    def run(self):
        try:
            for i,row in enumerate(self.rows):self.row_result.emit(i,proxy_health.test(row))
            self.completed.emit()
        except Exception as exc:self.failed.emit(str(exc))
def install(window_class):
    if getattr(window_class,"_network_identity_gui_installed",False):return
    ob=window_class.build_ui;orr=window_class.refresh
    def tab(self):
        p=QWidget();l=QVBoxLayout(p);g=QLabel("Proxyleri test edin, sonra hesaplara sabit kilitleyin. Aynı browser-context IP doğrulaması yayın öncesi tekrar yapılır.");g.setWordWrap(True);l.addWidget(g);r=QHBoxLayout();self.proxy_scheme=QComboBox();self.proxy_scheme.addItems(["http","https","socks5"]);self.pacing_seconds=QSpinBox();self.pacing_seconds.setRange(30,900);self.pacing_seconds.setValue(publication_pacing.get_seconds());r.addWidget(QLabel("Tip"));r.addWidget(self.proxy_scheme);r.addWidget(QLabel("Bekleme"));r.addWidget(self.pacing_seconds);l.addLayout(r);self.proxy_list_input=QPlainTextEdit();l.addWidget(self.proxy_list_input);a=QHBoxLayout();test=QPushButton("PROXY TEST");test.clicked.connect(self.test_proxy_list);assign=QPushButton("TESTİ GEÇENLERİ ATA");assign.clicked.connect(self.assign_proxy_list);reset=QPushButton("Seçili profil kilidini sıfırla");reset.clicked.connect(self.reset_selected_profile);[a.addWidget(x) for x in (test,assign,reset)];l.addLayout(a);self.proxy_mapping=QTableWidget(0,7);self.proxy_mapping.setHorizontalHeaderLabels(["Sıra","Hesap","Proxy","Test","IP","Ülke/ms","Risk"]);l.addWidget(self.proxy_mapping);self.ab_channel=QComboBox();self.ab_channel.addItems(["web","phone"]);self.ab_views=QSpinBox();self.ab_views.setMaximum(1000000000);self.ab_public=QCheckBox("Public");self.ab_fyf=QCheckBox("FYF uygun");ab=QHBoxLayout();[ab.addWidget(x) for x in (QLabel("A/B"),self.ab_channel,self.ab_views,self.ab_public,self.ab_fyf)];save=QPushButton("A/B SONUCU KAYDET");save.clicked.connect(self.save_ab_result);ab.addWidget(save);l.addLayout(ab);self.proxy_status=QLabel("Hazır");l.addWidget(self.proxy_status);self._rows=[];self._results={};return p
    def refresh_map(self):
        profiles=self.account_names();self.proxy_mapping.setRowCount(max(len(profiles),len(self._rows)))
        for i in range(self.proxy_mapping.rowCount()):
            profile=profiles[i] if i<len(profiles) else "";identity=network_identity.load(profile) if profile else (self._rows[i] if i<len(self._rows) else network_identity.NetworkIdentity());res=self._results.get(i) or (proxy_health.latest(identity) if identity.server else None);vals=[str(i+1),profile,identity.server or "Doğrudan","GEÇTİ" if res and res.ok else "BAŞARISIZ" if res else "Yok",res.exit_ip if res else "",f"{res.country_code}/{res.median_latency_ms}" if res else "",",".join(res.risk_flags) if res else ""]
            for c,v in enumerate(vals):self.proxy_mapping.setItem(i,c,QTableWidgetItem(v))
    def test_proxy_list(self):
        try:self._rows=network_identity.parse_proxy_list(self.proxy_list_input.toPlainText(),self.proxy_scheme.currentText());self._results={};w=ProxyTestWorker(self._rows,self);self.proxy_worker=w;w.row_result.connect(lambda i,x:(self._results.__setitem__(i,x),refresh_map(self)));w.completed.connect(lambda:self.proxy_status.setText("Proxy testi tamamlandı"));w.failed.connect(lambda x:QMessageBox.critical(self,"Test",x));w.start()
        except Exception as exc:QMessageBox.critical(self,"Proxy",str(exc))
    def assign_proxy_list(self):
        try:publication_pacing.set_seconds(self.pacing_seconds.value());network_identity.assign_in_order(self.account_names(),self._rows);refresh_map(self)
        except Exception as exc:QMessageBox.critical(self,"Atama",str(exc))
    def reset_selected_profile(self):
        row=self.proxy_mapping.currentRow()
        if row<0 or row>=len(self.account_names()):return
        profile=self.account_names()[row];network_identity.delete(profile);profile_integrity.reset(profile);refresh_map(self)
    def save_ab_result(self):
        row=self.proxy_mapping.currentRow()
        if row<0 or row>=len(self.account_names()):QMessageBox.warning(self,"A/B","Profil seçin");return
        p=self.account_names()[row];ab_diagnostics.record(p,self.ab_channel.currentText(),self.ab_views.value(),self.ab_public.isChecked(),self.ab_fyf.isChecked());self.proxy_status.setText(ab_diagnostics.summary(p))
    def build(self):ob(self);self.network_identity_page=tab(self);self.tabs.addTab(self.network_identity_page,"Proxy ve A/B");refresh_map(self)
    def refresh(self):orr(self);refresh_map(self) if hasattr(self,"proxy_mapping") else None
    for n,v in {"build_ui":build,"refresh":refresh,"test_proxy_list":test_proxy_list,"assign_proxy_list":assign_proxy_list,"reset_selected_profile":reset_selected_profile,"save_ab_result":save_ab_result}.items():setattr(window_class,n,v)
    window_class._network_identity_gui_installed=True
