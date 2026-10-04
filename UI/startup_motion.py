"""Read native motion preferences once at boot; no background polling or dependency."""
from __future__ import annotations

import os
import platform
import subprocess


def startup_redesign_enabled() -> bool:
    return os.environ.get("PPF_STUDIO_STARTUP", "1").strip().lower() not in {"0", "false", "off", "no"}


def reduced_motion_requested() -> bool:
    override = os.environ.get("PPF_REDUCED_MOTION", "").strip().lower()
    if override in {"1", "true", "on", "yes"}:
        return True
    # An explicit false override must not defeat an OS accessibility preference.
    system = platform.system()
    try:
        if system == "Windows":
            import ctypes
            enabled = ctypes.c_int(1)
            if ctypes.windll.user32.SystemParametersInfoW(0x1042, 0, ctypes.byref(enabled), 0):
                return not bool(enabled.value)
        elif system == "Darwin":
            result = subprocess.run(
                ["/usr/bin/defaults", "read", "com.apple.universalaccess", "reduceMotion"],
                capture_output=True, text=True, timeout=0.25, check=False,
            )
            return result.returncode == 0 and result.stdout.strip().lower() in {"1", "true", "yes"}
        elif system == "Linux":
            result = subprocess.run(
                ["gsettings", "get", "org.gnome.desktop.interface", "enable-animations"],
                capture_output=True, text=True, timeout=0.25, check=False,
            )
            return result.returncode == 0 and result.stdout.strip().lower() == "false"
    except (OSError, subprocess.SubprocessError, AttributeError):
        pass
    return False
