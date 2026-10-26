import os
import sys

# Ensure backend directory is in sys.path
backend_dir = os.path.dirname(os.path.abspath(__file__))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

import webview
from camera import CameraService
from stream_server import StreamServer
from tray import SystemTrayManager


WINDOW_WIDTH = 360
WINDOW_HEIGHT = 270

def get_resource_path(relative_path):
    """Gets absolute path to resources, compatible with PyInstaller (onefile & onedir) and dev."""
    # 1. PyInstaller _MEIPASS (onefile mode)
    if hasattr(sys, '_MEIPASS'):
        p = os.path.join(sys._MEIPASS, relative_path)
        if os.path.exists(p):
            return p
    # 2. Alongside sys.executable (onedir mode)
    exe_dir = os.path.dirname(os.path.abspath(sys.executable))
    p = os.path.join(exe_dir, relative_path)
    if os.path.exists(p):
        return p
    # 3. Inside macOS app bundle Resources
    p = os.path.join(exe_dir, '..', 'Resources', relative_path)
    if os.path.exists(p):
        return os.path.abspath(p)
    # 4. Standard development mode relative to workspace root
    root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    p = os.path.join(root_dir, relative_path)
    if os.path.exists(p):
        return p
    return os.path.join(root_dir, relative_path)


class DesktopApi:
    def __init__(self, camera_service, stream_port, toggle_fn, hide_fn, quit_fn):
        self.camera_service = camera_service
        self.stream_port = stream_port
        self.toggle_fn = toggle_fn
        self.hide_fn = hide_fn
        self.quit_fn = quit_fn

    def get_config(self):
        return {
            "stream_url": f"http://127.0.0.1:{self.stream_port}/video_feed",
            "stream_port": self.stream_port,
            "platform": sys.platform,
            "width": WINDOW_WIDTH,
            "height": WINDOW_HEIGHT
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


    def hide_window(self):
        self.hide_fn()
        return {"status": "hidden"}

    def quit_app(self):
        self.quit_fn()
        return {"status": "quitting"}

def main():
    # Automatically detect if running as a frozen PyInstaller bundle or from source
    IS_BUNDLED = getattr(sys, 'frozen', False)


    # Initialize OpenCV camera and streaming server (serves both MJPEG video feed and frontend dist)
    dist_dir = get_resource_path('frontend/dist')
    camera_service = CameraService()
    stream_server = StreamServer(camera_service, static_dir=dist_dir)
    stream_port = stream_server.start()

    window_state = {
        "visible": True,
        "window": None
    }

    def on_toggle_tray():
        w = window_state["window"]
        if not w:
            return

        if window_state["visible"]:
            w.hide()
            window_state["visible"] = False
        else:
            # Reposition right next to tray icon
            x, y = tray_manager.get_target_position(WINDOW_WIDTH, WINDOW_HEIGHT)
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
        camera_service.stop()
        w = window_state["window"]
        if w:
            try:
                w.destroy()
            except Exception:
                pass
        sys.exit(0)

    tray_manager = SystemTrayManager(on_toggle=on_toggle_tray, on_quit=on_quit_app)

    api = DesktopApi(
        camera_service=camera_service,
        stream_port=stream_port,
        toggle_fn=on_toggle_tray,
        hide_fn=on_hide_window,
        quit_fn=on_quit_app
    )

    def is_dev_server_running(host='127.0.0.1', port=5173):
        import socket
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(0.3)
            s.connect((host, port))
            s.close()
            return True
        except Exception:
            return False

    # If running from source and dev server is up, use Vite HMR; otherwise use built dist
    if not IS_BUNDLED and is_dev_server_running():
        url = f'http://localhost:5173?stream_port={stream_port}'
    else:
        url = f'http://127.0.0.1:{stream_port}/?stream_port={stream_port}'



    initial_x, initial_y = tray_manager.get_target_position(WINDOW_WIDTH, WINDOW_HEIGHT)

    # Create small floating rounded rectangle window
    window = webview.create_window(
        title='EyeDoc Camera',
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
        shadow=True
    )
    window_state["window"] = window

    def on_window_closing():
        # Prevent app exit when window is closed; hide to tray instead
        on_hide_window()
        return False

    window.events.closing += on_window_closing

    def on_gui_ready():
        if sys.platform == 'darwin':
            try:
                from AppKit import NSApp
                from PyObjCTools import AppHelper
                AppHelper.callAfter(tray_manager.setup_tray)
                AppHelper.callAfter(lambda: NSApp.activateIgnoringOtherApps_(True))
            except Exception as e:
                print(f"[App] Failed to init macOS tray via AppHelper: {e}")
                tray_manager.setup_tray()
        else:
            tray_manager.setup_tray()

    webview.start(on_gui_ready, debug=not IS_BUNDLED)


if __name__ == '__main__':
    main()
