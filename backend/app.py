
import os
import signal
import sys
import threading

# Prevent matplotlib from trying to write to non-writable directories
os.environ.setdefault("MPLCONFIGDIR", "/tmp/eyedoc_mpl")

# Ensure backend directory is in sys.path
backend_dir = os.path.dirname(os.path.abspath(__file__))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

import webview

from camera import CameraService
from stream_server import StreamServer
from blink_counter_server import BlinkCounterServer
from tray import SystemTrayManager


WINDOW_WIDTH = 360
WINDOW_HEIGHT = 270


def get_resource_path(relative_path):
    """Resolve resource paths for development and PyInstaller builds."""
    search_dirs = []

    # 1. PyInstaller _MEIPASS (onefile or onedir runtime dir)
    if hasattr(sys, "_MEIPASS"):
        search_dirs.append(sys._MEIPASS)

    # 2. Alongside executable (onedir mode, Contents/MacOS)
    exe_dir = os.path.dirname(os.path.abspath(sys.executable))
    search_dirs.append(exe_dir)

    # 3. macOS app bundle Resources (Contents/Resources)
    search_dirs.append(os.path.abspath(os.path.join(exe_dir, "..", "Resources")))

    # 4. macOS app bundle Frameworks (Contents/Frameworks)
    search_dirs.append(os.path.abspath(os.path.join(exe_dir, "..", "Frameworks")))

    # 5. Project root (parent of backend/) and backend/
    root_dir = os.path.dirname(backend_dir)
    search_dirs.append(root_dir)
    search_dirs.append(backend_dir)

    # 6. Current working directory
    search_dirs.append(os.path.abspath("."))

    # Variants of relative path to try (e.g. with/without 'backend/' prefix)
    rel_variants = [relative_path]
    if relative_path.startswith("backend/"):
        rel_variants.append(relative_path[len("backend/"):])

    for base in search_dirs:
        for rel in rel_variants:
            candidate = os.path.join(base, rel)
            if os.path.exists(candidate):
                return os.path.abspath(candidate)

    return os.path.abspath(relative_path)


class DesktopApi:
    def __init__(
        self,
        camera_service,
        stream_port,
        blink_port,
        toggle_fn,
        hide_fn,
        quit_fn,
    ):
        self.camera_service = camera_service
        self.stream_port = stream_port
        self.blink_port = blink_port
        self.toggle_fn = toggle_fn
        self.hide_fn = hide_fn
        self.quit_fn = quit_fn

    def get_config(self):
        """Configuration exposed to the PyWebView frontend."""
        return {
            # Existing camera configuration
            "stream_url": (
                f"http://127.0.0.1:{self.stream_port}/video_feed"
            ),
            "stream_port": self.stream_port,

            # Blink counter configuration
            "blink_port": self.blink_port,
            "blink_stream_url": (
                f"http://127.0.0.1:{self.blink_port}/video_feed"
            ),
            "blink_frame_url": (
                f"http://127.0.0.1:{self.blink_port}/frame"
            ),
            "blink_count_url": (
                f"http://127.0.0.1:{self.blink_port}/count"
            ),
            "blink_status_url": (
                f"http://127.0.0.1:{self.blink_port}/status"
            ),
            "blink_reset_url": (
                f"http://127.0.0.1:{self.blink_port}/reset"
            ),

            "platform": sys.platform,
            "width": WINDOW_WIDTH,
            "height": WINDOW_HEIGHT,
        }

    def get_camera_status(self):
        return self.camera_service.get_status()

    def toggle_mirror(self):
        return self.camera_service.toggle_mirror()

    def toggle_camera(self):
        return self.camera_service.toggle_streaming()

    def retry_camera(self):
        self.camera_service.retry_connection()
        return {"status": "retrying"}

    def switch_camera(self):
        new_index = self.camera_service.switch_camera()
        return {"camera_index": new_index}

    def get_blink_status(self):
        """Get blink statistics directly through the PyWebView API."""
        return self._blink_server.get_status()

    def reset_blink_count(self):
        """Reset lifetime and current interval counters."""
        return self._blink_server.reset_counts()

    def hide_window(self):
        self.hide_fn()
        return {"status": "hidden"}

    def quit_app(self):
        self.quit_fn()
        return {"status": "quitting"}

    def set_blink_server(self, blink_server):
        self._blink_server = blink_server


def main():
    # Detect PyInstaller bundle
    IS_BUNDLED = getattr(sys, "frozen", False)

    # --------------------------------------------------
    # Initialize the existing camera service and server
    # --------------------------------------------------
    dist_dir = get_resource_path("frontend/dist")

    camera_service = CameraService()

    stream_server = StreamServer(
        camera_service,
        static_dir=dist_dir,
    )
    stream_port = stream_server.start()

    # --------------------------------------------------
    # Initialize blink counter using the SAME camera
    # --------------------------------------------------
    model_path = get_resource_path("backend/models/face_landmarker.task")
    print(
        f"[App] Face Landmarker model: {model_path} "
        f"(exists={os.path.exists(model_path)})"
    )

    blink_server = BlinkCounterServer(
        camera_service=camera_service,
        warning_threshold=12,
        interval_seconds=60,
        model_path=model_path,
    )
    blink_port = blink_server.start()

    print(
        f"[App] Camera server: "
        f"http://127.0.0.1:{stream_port}"
    )
    print(
        f"[App] Blink server: "
        f"http://127.0.0.1:{blink_port}"
    )
    print(
        f"[App] Blink status: "
        f"http://127.0.0.1:{blink_port}/count"
    )

    window_state = {
        "visible": True,
        "window": None,
    }

    tray_manager = None
    is_quitting = False

    # --------------------------------------------------
    # Window and application lifecycle
    # --------------------------------------------------
    def on_toggle_tray():
        w = window_state["window"]

        if not w:
            return

        if window_state["visible"]:
            w.hide()
            window_state["visible"] = False
        else:
            # Reposition next to the system tray icon
            x, y = tray_manager.get_target_position(
                WINDOW_WIDTH,
                WINDOW_HEIGHT,
            )

            try:
                w.move(x, y)
            except Exception:
                pass

            w.show()

            try:
                w.restore()
            except Exception:
                pass

            window_state["visible"] = True

    def on_hide_window():
        w = window_state["window"]

        if w:
            w.hide()
            window_state["visible"] = False

    def on_quit_app():
        nonlocal is_quitting
        if is_quitting:
            return
        is_quitting = True
        print("[App] Shutting down...")

        def _cleanup():
            # Stop blink processing before stopping the camera
            try:
                blink_server.stop()
            except Exception as exc:
                print(f"[App] Blink server shutdown error: {exc}")

            try:
                camera_service.stop()
            except Exception as exc:
                print(f"[App] Camera shutdown error: {exc}")

            w = window_state.get("window")
            if w:
                try:
                    w.destroy()
                except Exception:
                    pass

            if sys.platform == "darwin":
                try:
                    from AppKit import NSApp
                    from PyObjCTools import AppHelper

                    AppHelper.callAfter(lambda: NSApp.terminate_(None))
                except Exception:
                    pass

            # Safe exit after brief delay to allow threads and sockets to close
            import time
            time.sleep(0.3)
            os._exit(0)

        threading.Thread(target=_cleanup, name="ShutdownThread", daemon=True).start()

    tray_manager = SystemTrayManager(
        on_toggle=on_toggle_tray,
        on_quit=on_quit_app,
    )

    # --------------------------------------------------
    # PyWebView JavaScript API
    # --------------------------------------------------
    api = DesktopApi(
        camera_service=camera_service,
        stream_port=stream_port,
        blink_port=blink_port,
        toggle_fn=on_toggle_tray,
        hide_fn=on_hide_window,
        quit_fn=on_quit_app,
    )

    api.set_blink_server(blink_server)

    # --------------------------------------------------
    # Detect Vite development server
    # --------------------------------------------------
    def is_dev_server_running(
        host="127.0.0.1",
        port=5173,
    ):
        import socket

        try:
            with socket.socket(
                socket.AF_INET,
                socket.SOCK_STREAM,
            ) as s:
                s.settimeout(0.3)
                s.connect((host, port))
                return True
        except Exception:
            return False

    # Preserve development/production frontend behavior.
    query = (
        f"stream_port={stream_port}"
        f"&blink_port={blink_port}"
    )

    if not IS_BUNDLED and is_dev_server_running():
        url = f"http://localhost:5173/?{query}"
    else:
        url = (
            f"http://127.0.0.1:{stream_port}/"
            f"?{query}"
        )

    # --------------------------------------------------
    # Create the existing floating PyWebView window
    # --------------------------------------------------
    initial_x, initial_y = tray_manager.get_target_position(
        WINDOW_WIDTH,
        WINDOW_HEIGHT,
    )

    window = webview.create_window(
        title="EyeDoc Camera",
        url=url,
        js_api=api,
        width=WINDOW_WIDTH,
        height=WINDOW_HEIGHT,
        x=initial_x,
        y=initial_y,
        resizable=False,
        frameless=True,
        transparent=True,
        on_top=True,
        shadow=True,
    )

    window_state["window"] = window

    def on_window_closing():
        if is_quitting:
            return True
        # Closing hides the window rather than exiting the app.
        on_hide_window()
        return False

    window.events.closing += on_window_closing

    # Clean signal handling
    def _sig_handler(sig, frame):
        on_quit_app()

    try:
        signal.signal(signal.SIGINT, _sig_handler)
        signal.signal(signal.SIGTERM, _sig_handler)
    except Exception:
        pass

    def on_gui_ready():
        if sys.platform == "darwin":
            try:
                from AppKit import NSApp
                from PyObjCTools import AppHelper

                AppHelper.callAfter(tray_manager.setup_tray)
                AppHelper.callAfter(
                    lambda: NSApp.activateIgnoringOtherApps_(True)
                )
            except Exception as exc:
                print(
                    "[App] Failed to initialize macOS tray "
                    f"via AppHelper: {exc}"
                )
                tray_manager.setup_tray()
        else:
            tray_manager.setup_tray()

    webview.start(
        on_gui_ready,
        debug=not IS_BUNDLED,
    )


if __name__ == "__main__":
    main()
