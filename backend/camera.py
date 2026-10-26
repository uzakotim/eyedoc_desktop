import cv2
import math
import numpy as np
import sys
import threading
import time

class CameraService:
    def __init__(self, camera_index=0):
        self.camera_index = camera_index
        self.cap = None
        self.is_running = True
        self.is_streaming = True
        self.mirror = True
        self.frame_lock = threading.Lock()
        self.latest_jpeg = None
        self.connected = False
        self.error_message = None
        self.fps = 0.0
        self.anim_step = 0
        self.resolution = (640, 480)

        # Start background capture thread
        self.thread = threading.Thread(target=self._capture_loop, daemon=True)
        self.thread.start()

    def _open_camera(self):
        """Attempts to open camera using platform-appropriate backend."""
        try:
            if sys.platform == 'darwin':
                # Try AVFoundation backend on macOS
                cap = cv2.VideoCapture(self.camera_index, cv2.CAP_AVFOUNDATION)
                if not cap.isOpened():
                    cap = cv2.VideoCapture(self.camera_index)
            elif sys.platform.startswith('win'):
                # Try DirectShow backend on Windows
                cap = cv2.VideoCapture(self.camera_index, cv2.CAP_DSHOW)
                if not cap.isOpened():
                    cap = cv2.VideoCapture(self.camera_index)
            else:
                cap = cv2.VideoCapture(self.camera_index)

            if cap.isOpened():
                # Read a few warmup frames so auto-exposure engages properly
                for _ in range(3):
                    cap.read()

                w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 640)
                h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 480)
                self.resolution = (w, h)
                return cap
            else:
                return None
        except Exception as e:
            self.error_message = str(e)
            return None

    def _create_fallback_frame(self, message=None):
        """Generates an animated high-tech placeholder frame when camera is unavailable."""
        w, h = 640, 480
        img = np.zeros((h, w, 3), dtype=np.uint8)
        img[:] = (22, 20, 28)

        cx, cy = w // 2, h // 2 - 20
        self.anim_step = (self.anim_step + 1) % 360

        pulse = int(10 * math.sin(math.radians(self.anim_step * 2)))
        r1 = 70 + pulse
        r2 = 100 + pulse
        cv2.circle(img, (cx, cy), max(10, r1), (45, 38, 55), 2)
        cv2.circle(img, (cx, cy), max(20, r2), (35, 30, 45), 1)

        angle = math.radians(self.anim_step * 3)
        sx = int(cx + r1 * math.cos(angle))
        sy = int(cy + r1 * math.sin(angle))
        cv2.line(img, (cx, cy), (sx, sy), (180, 130, 255), 2)

        # Draw eye silhouette in center
        cv2.ellipse(img, (cx, cy), (32, 18), 0, 0, 360, (220, 210, 255), 2)
        cv2.circle(img, (cx, cy), 9, (190, 120, 255), -1)
        cv2.circle(img, (cx + 3, cy - 3), 3, (255, 255, 255), -1)

        title = f"EyeDoc Camera #{self.camera_index}"
        cv2.putText(img, title, (cx - 85, cy + 85), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (255, 255, 255), 2, cv2.LINE_AA)

        status_text = message or (self.error_message if self.error_message else "Connecting to camera...")
        cv2.putText(img, status_text, (cx - 130, cy + 115), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (160, 150, 180), 1, cv2.LINE_AA)

        ts = time.strftime("%H:%M:%S")
        cv2.putText(img, f"OpenCV • {ts}", (16, h - 16), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (100, 95, 115), 1, cv2.LINE_AA)

        _, buf = cv2.imencode('.jpg', img, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
        return buf.tobytes()

    def _capture_loop(self):
        last_time = time.time()
        fps_count = 0
        retry_interval = 2.0
        last_retry = 0.0

        while self.is_running:
            now = time.time()

            # Handle camera opening / reconnection
            if not self.connected or self.cap is None:
                if now - last_retry >= retry_interval:
                    last_retry = now
                    self.cap = self._open_camera()
                    if self.cap is not None:
                        self.connected = True
                        self.error_message = None
                    else:
                        self.connected = False
                        if not self.error_message:
                            self.error_message = f"Camera #{self.camera_index} not authorized / busy"

            # If streaming is paused by user
            if not self.is_streaming:
                jpeg = self._create_fallback_frame("Camera preview paused")
                with self.frame_lock:
                    self.latest_jpeg = jpeg
                time.sleep(0.1)
                continue

            if self.connected and self.cap is not None:
                ret, frame = self.cap.read()
                if ret and frame is not None:
                    # Downscale to max 640px wide for efficiency while preserving aspect ratio
                    h, w = frame.shape[:2]
                    if w > 640:
                        new_h = int(h * (640 / w))
                        frame = cv2.resize(frame, (640, new_h), interpolation=cv2.INTER_AREA)

                    # Apply mirror mode if enabled (standard for front webcams)
                    if self.mirror:
                        frame = cv2.flip(frame, 1)

                    # Encode to JPEG
                    ret_enc, buf = cv2.imencode('.jpg', frame, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
                    if ret_enc:
                        with self.frame_lock:
                            self.latest_jpeg = buf.tobytes()

                    # Calculate FPS
                    fps_count += 1
                    if now - last_time >= 1.0:
                        self.fps = round(fps_count / (now - last_time), 1)
                        fps_count = 0
                        last_time = now

                    # Sleep briefly to cap at ~30 FPS
                    time.sleep(0.015)
                    continue
                else:
                    # Frame read failure
                    self.connected = False
                    if self.cap:
                        try:
                            self.cap.release()
                        except Exception:
                            pass
                        self.cap = None

            # Fallback frame when disconnected
            jpeg = self._create_fallback_frame()
            with self.frame_lock:
                self.latest_jpeg = jpeg
            time.sleep(0.05)

    def get_jpeg(self):
        with self.frame_lock:
            if self.latest_jpeg is not None:
                return self.latest_jpeg
        return self._create_fallback_frame()

    def generate_mjpeg(self):
        """Generator yielding MJPEG multipart frames with strict WebKit Content-Length."""
        while self.is_running:
            jpeg = self.get_jpeg()
            yield (
                b'--frame\r\n'
                b'Content-Type: image/jpeg\r\n'
                b'Content-Length: ' + str(len(jpeg)).encode('ascii') + b'\r\n\r\n'
                + jpeg + b'\r\n'
            )
            time.sleep(0.033)

    def toggle_mirror(self):
        self.mirror = not self.mirror
        return self.mirror

    def toggle_streaming(self):
        self.is_streaming = not self.is_streaming
        return self.is_streaming

    def switch_camera(self):
        """Switches between camera index 0 and 1."""
        with self.frame_lock:
            if self.cap:
                try:
                    self.cap.release()
                except Exception:
                    pass
                self.cap = None
            self.camera_index = 1 if self.camera_index == 0 else 0
            self.connected = False
            self.error_message = f"Switching to camera #{self.camera_index}..."
        return self.camera_index

    def retry_connection(self):
        if self.cap:
            try:
                self.cap.release()
            except Exception:
                pass
            self.cap = None
        self.connected = False
        self.error_message = None

    def get_status(self):
        return {
            "connected": self.connected,
            "streaming": self.is_streaming,
            "mirror": self.mirror,
            "camera_index": self.camera_index,
            "fps": self.fps,
            "resolution": list(self.resolution),
            "error": self.error_message
        }

    def stop(self):
        self.is_running = False
        if self.cap:
            try:
                self.cap.release()
            except Exception:
                pass
            self.cap = None
