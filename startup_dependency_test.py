from __future__ import annotations

import builtins
import importlib
from types import SimpleNamespace
from unittest.mock import patch

import qa_runtime_dependencies


def main() -> None:
 completed=SimpleNamespace(returncode=0);state={"calls":0}
 def fake_missing():state["calls"]+=1;return ["numpy","cv2"] if state["calls"]==1 else []
 with patch.object(qa_runtime_dependencies,"missing_modules",side_effect=fake_missing),patch.object(qa_runtime_dependencies.subprocess,"run",return_value=completed) as run:
  assert qa_runtime_dependencies.ensure_dependencies();command=run.call_args.args[0]
  assert command[:4]==[qa_runtime_dependencies.sys.executable,"-m","pip","install"]
  assert "opencv-python-headless>=4.10,<5" in command and "numpy>=2.0,<3" in command
 original_import=builtins.__import__
 def blocked(name,*args,**kwargs):
  if name in {"cv2","numpy"}:raise ModuleNotFoundError(name)
  return original_import(name,*args,**kwargs)
 with patch("builtins.__import__",side_effect=blocked):
  module=importlib.reload(importlib.import_module("originality_qa"));assert module.hamming(0b1010,0b0011)==2
  try:module.inspect_video(SimpleNamespace(expanduser=lambda:None))
  except Exception as exc:assert "OpenCV/NumPy eksik" in str(exc)
 print("OK: app importu cv2 olmadan çalışıyor ve uniquizer aktif venv'i self-heal ediyor")

if __name__=="__main__":main()
