from __future__ import annotations

"""Local quality gates loaded lazily so GUI startup never depends on cv2."""

from dataclasses import dataclass
from pathlib import Path
from typing import Any

class OriginalityQAError(RuntimeError): pass

@dataclass(frozen=True)
class OriginalityReport:
 duration: float
 sampled_frames: int
 static_ratio: float
 qr_detected: bool
 signature: tuple[int, ...]

def _libraries():
 try:
  import cv2
  import numpy as np
 except (ImportError, ModuleNotFoundError) as exc:
  raise OriginalityQAError(
   "OpenCV/NumPy eksik. update_project.ps1 çalıştırın veya aktif venv ile "
   "python -m pip install -r requirements.txt"
  ) from exc
 return cv2, np

def _dhash(frame: Any) -> int:
 cv2, _ = _libraries(); gray=cv2.cvtColor(frame,cv2.COLOR_BGR2GRAY); small=cv2.resize(gray,(9,8),interpolation=cv2.INTER_AREA); diff=small[:,1:]>small[:,:-1]; value=0
 for bit in diff.flatten(): value=(value<<1)|int(bit)
 return value

def hamming(left:int,right:int)->int:return (left^right).bit_count()
def signature_distance(left:tuple[int,...],right:tuple[int,...])->float:
 if not left or not right:return 0.0
 count=min(len(left),len(right));return sum(hamming(left[i],right[i]) for i in range(count))/count

def inspect_video(path:Path,samples:int=16)->OriginalityReport:
 cv2,np=_libraries();path=path.expanduser().resolve();capture=cv2.VideoCapture(str(path))
 if not capture.isOpened():raise OriginalityQAError(f"Video OpenCV ile açılamadı: {path.name}")
 try:
  frame_count=int(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0);fps=float(capture.get(cv2.CAP_PROP_FPS) or 0);duration=frame_count/fps if frame_count>0 and fps>0 else 0.0
  if frame_count<2 or duration<=0:raise OriginalityQAError(f"Video süresi/frame sayısı okunamadı: {path.name}")
  detector=cv2.QRCodeDetector();positions=np.linspace(0,frame_count-1,min(samples,frame_count),dtype=int);signatures=[];previous=None;static=0;transitions=0;qr=False
  for position in positions:
   capture.set(cv2.CAP_PROP_POS_FRAMES,int(position));ok,frame=capture.read()
   if not ok or frame is None:continue
   signatures.append(_dhash(frame));gray=cv2.resize(cv2.cvtColor(frame,cv2.COLOR_BGR2GRAY),(160,90),interpolation=cv2.INTER_AREA)
   if previous is not None:
    transitions+=1
    if float(cv2.absdiff(previous,gray).mean())<1.6:static+=1
   previous=gray
   try:
    decoded,_,_=detector.detectAndDecode(frame);qr=qr or bool(decoded)
   except cv2.error:pass
  return OriginalityReport(duration,len(signatures),static/transitions if transitions else 1.0,qr,tuple(signatures))
 finally:capture.release()

def assert_source_eligible(path:Path)->OriginalityReport:
 report=inspect_video(path);failures=[]
 if report.duration<8.0:failures.append("kaynak video 8 saniyeden kısa")
 if report.sampled_frames<8:failures.append("yeterli görüntü karesi örneklenemedi")
 if report.static_ratio>0.70:failures.append("video büyük ölçüde sabit/düşük hareketli")
 if report.qr_detected:failures.append("videoda QR kod algılandı")
 if failures:raise OriginalityQAError("Özgünlük/kalite ön kontrolü başarısız: "+"; ".join(failures))
 return report

def assert_output_eligible(path:Path,previous:list[OriginalityReport])->OriginalityReport:
 report=inspect_video(path)
 if report.duration<6.0:raise OriginalityQAError(f"{path.name}: çıktı 6 saniyeden kısa")
 if report.static_ratio>0.70:raise OriginalityQAError(f"{path.name}: çıktı düşük hareketli")
 if report.qr_detected:raise OriginalityQAError(f"{path.name}: çıktıda QR kod algılandı")
 for index,other in enumerate(previous,1):
  distance=signature_distance(report.signature,other.signature)
  if distance<6.0:raise OriginalityQAError(f"{path.name}: {index}. varyasyondan yeterince farklı değil (görsel mesafe {distance:.1f})")
 return report
