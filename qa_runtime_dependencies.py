from __future__ import annotations

"""Install and verify originality-QA dependencies in the active interpreter."""

import importlib
import subprocess
import sys
from collections.abc import Callable

REQUIRED = (
 ("numpy", "numpy>=2.0,<3"),
 ("cv2", "opencv-python-headless>=4.10,<5"),
)

class DependencyBootstrapError(RuntimeError):
 pass

def missing_modules() -> list[str]:
 missing: list[str] = []
 for module, _ in REQUIRED:
  try: importlib.import_module(module)
  except (ImportError, ModuleNotFoundError): missing.append(module)
 return missing

def ensure_dependencies(progress: Callable[[str], None] | None = None) -> bool:
 missing = missing_modules()
 if not missing: return False
 packages = [package for module, package in REQUIRED if module in missing]
 message = "Eksik video QA bağımlılıkları aktif venv'e kuruluyor: " + ", ".join(packages)
 if progress: progress(message)
 else: print(message, flush=True)
 completed = subprocess.run(
  [sys.executable, "-m", "pip", "install", "--disable-pip-version-check", *packages],
  text=True,
 )
 if completed.returncode:
  raise DependencyBootstrapError(
   "OpenCV/NumPy otomatik kurulamadı. Aktif venv ile çalıştırın: "
   "python -m pip install -r requirements.txt"
  )
 importlib.invalidate_caches()
 still_missing = missing_modules()
 if still_missing:
  raise DependencyBootstrapError("Kurulum sonrası modüller yüklenemedi: " + ", ".join(still_missing))
 return True
