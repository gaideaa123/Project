from __future__ import annotations

"""Install and verify optional originality-QA dependencies in the active venv."""

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
  try:
   importlib.import_module(module)
  except (ImportError, ModuleNotFoundError):
   missing.append(module)
 return missing

def ensure_dependencies(progress: Callable[[str], None] | None = None) -> bool:
 """Install only missing packages with the exact interpreter running app_tr."""
 missing = missing_modules()
 if not missing:
  return False
 packages = [package for module, package in REQUIRED if module in missing]
 message = "Eksik video QA bağımlılıkları kuruluyor: " + ", ".join(packages)
 if progress:
  progress(message)
 else:
  print(message, flush=True)
 command = [sys.executable, "-m", "pip", "install", "--disable-pip-version-check", *packages]
 completed = subprocess.run(command, text=True)
 if completed.returncode:
  raise DependencyBootstrapError(
   "OpenCV/NumPy otomatik kurulamadı. Aynı terminalde şunu çalıştırın: "
   f"{sys.executable} -m pip install -r requirements.txt"
  )
 importlib.invalidate_caches()
 still_missing = missing_modules()
 if still_missing:
  raise DependencyBootstrapError(
   "Kurulum tamamlandı fakat modüller yüklenemedi: " + ", ".join(still_missing)
  )
 return True
