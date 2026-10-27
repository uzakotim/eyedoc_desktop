"""
macOS Notification helper for EyeDoc.
"""

from __future__ import annotations

import subprocess
import sys


def send_mac_notification(
    message: str = "Blink!",
    title: str = "EyeDoc",
    subtitle: str = "",
    sound: bool = True,
) -> bool:
    """Send a native macOS notification using AppleScript via osascript.

    Spawns asynchronously via subprocess.Popen so it never blocks the caller.
    """
    if sys.platform != "darwin":
        return False

    try:
        # Escape backslashes and double quotes for AppleScript string literals
        safe_message = message.replace("\\", "\\\\").replace('"', '\\"')
        safe_title = title.replace("\\", "\\\\").replace('"', '\\"')

        cmd_parts = [f'display notification "{safe_message}"']
        if safe_title:
            cmd_parts.append(f'with title "{safe_title}"')
        if subtitle:
            safe_subtitle = subtitle.replace("\\", "\\\\").replace('"', '\\"')
            cmd_parts.append(f'subtitle "{safe_subtitle}"')
        if sound:
            cmd_parts.append('sound name "default"')

        script = " ".join(cmd_parts)

        subprocess.Popen(
            ["/usr/bin/osascript", "-e", script],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return True
    except Exception as exc:
        print(f"[Notifications] Error sending macOS notification: {exc}")
        return False

