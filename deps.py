"""Makes sure Pillow is importable (the approvals workflow installs it; this is the safety net)."""

import importlib
import subprocess
import sys


def ensure_pillow() -> None:
    try:
        import PIL  # noqa: F401
        return
    except ImportError:
        pass
    for extra in (["--break-system-packages"], ["--user"], []):
        r = subprocess.run([sys.executable, "-m", "pip", "install", "--quiet", "Pillow==10.4.0", *extra],
                           capture_output=True, text=True)
        importlib.invalidate_caches()
        try:
            import PIL  # noqa: F401
            return
        except ImportError:
            print(f"[deps] pip install Pillow {' '.join(extra)} failed: {(r.stderr or r.stdout)[-200:]}")
    raise ImportError("Pillow could not be installed")


def ensure_numpy() -> None:
    """numpy is used to generate the Reel audio (the workflow installs it; this is the safety net)."""
    try:
        import numpy  # noqa: F401
        return
    except ImportError:
        pass
    for extra in (["--break-system-packages"], ["--user"], []):
        subprocess.run([sys.executable, "-m", "pip", "install", "--quiet", "numpy", *extra],
                       capture_output=True, text=True)
        importlib.invalidate_caches()
        try:
            import numpy  # noqa: F401
            return
        except ImportError:
            continue
    raise ImportError("numpy could not be installed")
