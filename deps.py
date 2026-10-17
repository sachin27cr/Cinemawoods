"""Installs Pillow on demand (the approvals workflow does not pre-install it, which keeps taps fast)."""

import subprocess
import sys


def ensure_pillow() -> None:
    try:
        import PIL  # noqa: F401
    except ImportError:
        subprocess.run([sys.executable, "-m", "pip", "install", "--quiet", "--break-system-packages",
                        "Pillow==10.4.0"], check=False)
