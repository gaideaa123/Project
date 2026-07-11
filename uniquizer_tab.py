from __future__ import annotations

"""Standalone cold-open TikTok uniquizer tab used directly by app_tr.py."""

from pathlib import Path

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import QFileDialog,QFormLayout,QHBoxLayout,QLabel,QLineEdit,QMessageBox,QProgressBar,QPushButton,QSpinBox,QVBoxLayout,QWidget

import qa_runtime_dependencies
import video_variants

class UniquizerWorker(QThread):
 progress=Signal(int);status=Signal(str);completed=Signal(object);failed=Signal(str)
 def __init__(self,source:Path,output:Path,count:int,parent=None):super().__init__(parent);self.source,self.output,self.count=source,output,count
 def run(self)->None:
  try:
   qa_runtime_dependencies.ensure_dependencies(self.status.emit)
   files=video_variants.create_variants(self.source,self.count,lambda percent,message:(self.progress.emit(percent),self.status.emit(message)),cold_open=True,output_dir=self.output)
   self.completed.emit([str(path) for path in files])
  except Exception as exc:self.failed.emit(str(exc))

class UniquizerTab(QWidget):
 outputs_ready=Signal(object)
 def __init__(self,parent=None):super().__init__(parent);self.worker=None;self.last_outputs=[];self._build()
 def _build(self)->None:
  layout=QVBoxLayout(self);title=QLabel("TikTok Cold-Open Uniquizer");title.setStyleSheet("font-size: 20px; font-weight: 700");layout.addWidget(title)
  note=QLabel("Input, output ve adet seç. Üretim bitince numaralı çıktılar profil sırasına otomatik dağıtılır.");note.setWordWrap(True);layout.addWidget(note);form=QFormLayout()
  self.input_video=QLineEdit();input_button=QPushButton("Input seç");input_button.clicked.connect(self.choose_input);input_row=QHBoxLayout();input_row.addWidget(self.input_video,1);input_row.addWidget(input_button);form.addRow("Input video",input_row)
  self.output_folder=QLineEdit();output_button=QPushButton("Output seç");output_button.clicked.connect(self.choose_output);output_row=QHBoxLayout();output_row.addWidget(self.output_folder,1);output_row.addWidget(output_button);form.addRow("Output folder",output_row)
  self.variant_count=QSpinBox();self.variant_count.setRange(1,100);self.variant_count.setValue(5);self.variant_count.setSuffix(" varyasyon");form.addRow("Varyasyon sayısı",self.variant_count);layout.addLayout(form)
  self.start_button=QPushButton("VİDEOYU UNIQUIZE ET + PROFİLLERE DAĞIT");self.start_button.setMinimumHeight(48);self.start_button.clicked.connect(self.start);layout.addWidget(self.start_button)
  self.progress=QProgressBar();layout.addWidget(self.progress);self.status=QLabel("Hazır");self.status.setWordWrap(True);layout.addWidget(self.status);layout.addStretch()
 def choose_input(self)->None:
  filename,_=QFileDialog.getOpenFileName(self,"Input video seç","","Video (*.mp4 *.mov *.mkv *.webm *.m4v)")
  if filename:
   source=Path(filename).resolve();self.input_video.setText(str(source))
   if not self.output_folder.text().strip():self.output_folder.setText(str(source.parent/f"{source.stem}-cold-open-varyasyonlar"))
 def choose_output(self)->None:
  selected=QFileDialog.getExistingDirectory(self,"Output folder seç",self.output_folder.text().strip() or str(Path.home()))
  if selected:self.output_folder.setText(str(Path(selected).resolve()))
 def start(self)->None:
  if self.worker and self.worker.isRunning():return
  source=Path(self.input_video.text().strip()).expanduser()
  if not source.is_file():QMessageBox.warning(self,"Input bulunamadı","Geçerli bir input video seçin.");return
  output=Path(self.output_folder.text().strip()).expanduser() if self.output_folder.text().strip() else source.parent/f"{source.stem}-cold-open-varyasyonlar"
  try:output=output.resolve();output.mkdir(parents=True,exist_ok=True)
  except OSError as exc:QMessageBox.critical(self,"Output açılamadı",str(exc));return
  self.output_folder.setText(str(output));self.start_button.setEnabled(False);self.progress.setValue(0);self.status.setText("Bağımlılıklar ve varyasyonlar hazırlanıyor...")
  self.worker=UniquizerWorker(source.resolve(),output,self.variant_count.value(),self);self.worker.progress.connect(self.progress.setValue);self.worker.status.connect(self.status.setText);self.worker.completed.connect(self._completed);self.worker.failed.connect(self._failed);self.worker.finished.connect(self._finished);self.worker.start()
 def _completed(self,files:object)->None:
  self.last_outputs=list(files or [])
  if not self.last_outputs:self._failed("Uniquizer çıktı üretmedi");return
  self.status.setText(f"{len(self.last_outputs)} varyasyon hazır; profillere dağıtılıyor");self.outputs_ready.emit(list(self.last_outputs))
 def _failed(self,detail:str)->None:self.status.setText("Uniquizer başarısız");QMessageBox.critical(self,"Cold-open üretim hatası",detail)
 def _finished(self)->None:
  self.start_button.setEnabled(True);worker=self.worker;self.worker=None
  if worker:worker.deleteLater()
 def shutdown(self,timeout_ms:int=5000)->bool:return not self.worker or not self.worker.isRunning() or self.worker.wait(timeout_ms)
