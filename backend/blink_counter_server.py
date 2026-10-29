"""
EyeDoc blink counter server.

Requires:
    pip install opencv-python mediapipe bottle cheroot

Model:
    backend/models/face_landmarker.task

The server reuses CameraService.get_jpeg(); it does not open a second camera.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any, Optional

import cv2
import mediapipe as mp
import numpy as np
from bottle import Bottle, HTTPResponse, response
from cheroot.wsgi import Server as WSGIServer
import socket

try:
    from notifications import send_mac_notification, show_game_overlay
except ImportError:
    try:
        from backend.notifications import send_mac_notification, show_game_overlay
    except ImportError:
        def send_mac_notification(message="Blink!", title="EyeDoc", **kwargs):
            pass
        def show_game_overlay(*args, **kwargs):
            pass


# MediaPipe Face Mesh landmark indices used to calculate eye aspect ratio (EAR).
# Order: outer corner, upper outer, upper inner, inner corner, lower inner,
# lower outer.
LEFT_EYE_INDICES = (33, 160, 158, 133, 153, 144)
RIGHT_EYE_INDICES = (362, 385, 387, 263, 373, 380)



class BlinkCounterServer:
    def __init__(
        self,
        camera_service,
        host: str = "127.0.0.1",
        port: int = 0,
        warning_threshold: int = 12,
        interval_seconds: int = 60,
        ear_threshold: float = 0.21,
        min_closed_frames: int = 2,
        model_path: Optional[str] = None,
        notify_on_warning: bool = True,
        on_warning: Optional[Any] = None,
    ):
        self.camera_service = camera_service
        self.host = host
        self.port = int(port)
        self.warning_threshold = int(warning_threshold)
        self.interval_seconds = int(interval_seconds)
        self.ear_threshold = float(ear_threshold)
        self.min_closed_frames = max(1, int(min_closed_frames))
        self.notify_on_warning = bool(notify_on_warning)
        self.on_warning = on_warning

        self.model_path = Path(model_path) if model_path else (
            Path(__file__).resolve().parent / "models" / "face_landmarker.task"
        )

        self._lock = threading.RLock()
        self._stop_event = threading.Event()
        self._processing_thread: Optional[threading.Thread] = None
        self._server_thread: Optional[threading.Thread] = None
        self._http_server: Optional[WSGIServer] = None
        self._started = False

        self.blink_count = 0
        self.interval_blink_count = 0
        self.last_interval_count: Optional[int] = None
        self.last_interval_warning = False
        self.last_interval_end: Optional[float] = None
        self.interval_start_time = time.monotonic()

        self.closed_frames = 0
        self.eye_closed = False
        self._last_timestamp_ms = 0
        self._last_ear: Optional[float] = None
        self._last_frame_jpeg: Optional[bytes] = None
        self._last_frame_time = 0.0
        self._last_error: Optional[str] = None
        self._face_detected = False

        self.app = Bottle()
        self._register_routes()

    # ------------------------------------------------------------------
    # Public lifecycle
    # ------------------------------------------------------------------

    def start(self) -> int:
        """Start processing and HTTP server. Returns the selected TCP port."""
        if self._started:
            return self.port

        if not self.model_path.is_file():
            err_msg = (
                f"Face Landmarker model not found at: {self.model_path}\n"
                "Please ensure face_landmarker.task exists and is included in the build."
            )

        self._stop_event.clear()
        self._http_server = WSGIServer(
            (self.host, self.port),
            self.app,
            numthreads=8,
        )

        # Bind now so an ephemeral port (port=0) is resolved before returning.
        self._http_server.bind(socket.AF_INET, socket.SOCK_STREAM)
        # With port=0, read the actual port selected by the operating system.
        bound_address = self._http_server.socket.getsockname()
        self.port = int(bound_address[1])

        self._server_thread = threading.Thread(
            target=self._serve_http,
            name="BlinkCounterHTTP",
            daemon=True,
        )
        self._processing_thread = threading.Thread(
            target=self._processing_loop,
            name="BlinkCounterProcessing",
            daemon=True,
        )

        self._started = True
        self._server_thread.start()
        self._processing_thread.start()
        return self.port

    def stop(self) -> None:
        """Stop processing and the HTTP server."""
        self._stop_event.set()

        server = self._http_server
        if server is not None:
            try:
                server.stop()
            except Exception:
                pass

        if self._processing_thread and self._processing_thread.is_alive():
            self._processing_thread.join(timeout=1.0)

        if self._server_thread and self._server_thread.is_alive():
            self._server_thread.join(timeout=1.0)

        self._started = False

    def get_status(self) -> dict[str, Any]:
        with self._lock:
            elapsed = max(0.0, time.monotonic() - self.interval_start_time)
            remaining = max(0.0, self.interval_seconds - elapsed)
            return {
                "blink_count": self.blink_count,
                "total_blinks": self.blink_count,
                "interval_blink_count": self.interval_blink_count,
                "current_minute_blinks": self.interval_blink_count,
                "last_interval_count": self.last_interval_count,
                "last_interval_warning": self.last_interval_warning,
                "last_interval_end": self.last_interval_end,
                "warning_threshold": self.warning_threshold,
                "interval_seconds": self.interval_seconds,
                "time_remaining": round(remaining, 1),
                "face_detected": self._face_detected,
                "eye_aspect_ratio": (
                    round(self._last_ear, 3)
                    if self._last_ear is not None
                    else None
                ),
                "error": self._last_error,
            }

    def reset_counts(self) -> dict[str, Any]:
        with self._lock:
            self.blink_count = 0
            self.interval_blink_count = 0
            self.last_interval_count = None
            self.last_interval_warning = False
            self.last_interval_end = None
            self.interval_start_time = time.monotonic()
            self.closed_frames = 0
            self.eye_closed = False
            self._last_ear = None
        return {
            "reset": True,
            "blink_count": 0,
            "total_blinks": 0,
            "interval_blink_count": 0,
            "current_minute_blinks": 0,
            "last_interval_count": None,
            "last_interval_warning": False,
        }

    def get_latest_jpeg(self) -> Optional[bytes]:
        with self._lock:
            return self._last_frame_jpeg

    # ------------------------------------------------------------------
    # HTTP routes
    # ------------------------------------------------------------------

    def _register_routes(self) -> None:
        @self.app.hook("after_request")
        def _cors_headers():
            response.set_header("Access-Control-Allow-Origin", "*")
            response.set_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            response.set_header("Access-Control-Allow-Headers", "Origin, Content-Type, Accept")

        @self.app.route("/status", method=["GET", "OPTIONS"])
        def status_route():
            if self._is_options():
                return ""
            return self.get_status()

        @self.app.route("/count", method=["GET", "OPTIONS"])
        def count_route():
            if self._is_options():
                return ""
            s = self.get_status()
            return {
                "blink_count": s["blink_count"],
                "total_blinks": s["total_blinks"],
                "interval_blink_count": s["interval_blink_count"],
                "current_minute_blinks": s["current_minute_blinks"],
                "last_interval_count": s["last_interval_count"],
                "last_interval_warning": s["last_interval_warning"],
            }

        @self.app.route("/reset", method=["GET", "POST", "OPTIONS"])
        def reset_route():
            if self._is_options():
                return ""
            return self.reset_counts()

        @self.app.route("/notify_test", method=["GET", "POST", "OPTIONS"])
        def notify_test_route():
            if self._is_options():
                return ""
            return self.trigger_test_warning()

        @self.app.route("/snapshot.jpg", method=["GET", "OPTIONS"])
        @self.app.route("/frame", method=["GET", "OPTIONS"])
        def snapshot_route():
            if self._is_options():
                return ""
            frame = self.get_latest_jpeg()
            if not frame:
                return HTTPResponse(
                    status=503,
                    body="No processed camera frame available yet",
                    headers={"Content-Type": "text/plain; charset=utf-8"},
                )
            return HTTPResponse(
                body=frame,
                status=200,
                headers={
                    "Content-Type": "image/jpeg",
                    "Cache-Control": "no-store, no-cache, must-revalidate",
                    "Pragma": "no-cache",
                },
            )

        @self.app.route("/video_feed", method=["GET", "OPTIONS"])
        def video_feed_route():
            if self._is_options():
                return ""

            boundary = "frame"

            def generate():
                last_frame = None
                while not self._stop_event.is_set():
                    frame = self.get_latest_jpeg()
                    if frame and frame != last_frame:
                        last_frame = frame
                        yield (
                            b"--" + boundary.encode() + b"\r\n"
                            b"Content-Type: image/jpeg\r\n"
                            b"Content-Length: " + str(len(frame)).encode() + b"\r\n\r\n"
                            + frame + b"\r\n"
                        )
                    if self._stop_event.wait(0.03):
                        break

            return HTTPResponse(
                body=generate(),
                status=200,
                headers={
                    "Content-Type": f"multipart/x-mixed-replace; boundary={boundary}",
                    "Cache-Control": "no-cache, no-store, must-revalidate",
                    "Pragma": "no-cache",
                },
            )

    @staticmethod
    def _is_options() -> bool:
        if getattr(__import__("bottle"), "request").method == "OPTIONS":
            response.status = 204
            return True
        return False

    # ------------------------------------------------------------------
    # Background server / processing
    # ------------------------------------------------------------------

    def _serve_http(self) -> None:
        try:
            if self._http_server is not None:
                self._http_server.start()
        except Exception as exc:
            with self._lock:
                self._last_error = f"HTTP server error: {exc}"

    def _processing_loop(self) -> None:
        landmarker = None
        try:
            options = mp.tasks.vision.FaceLandmarkerOptions(
                base_options=mp.tasks.BaseOptions(
                    model_asset_path=str(self.model_path)
                ),
                running_mode=mp.tasks.vision.RunningMode.VIDEO,
                num_faces=1,
                min_face_detection_confidence=0.5,
                min_face_presence_confidence=0.5,
                min_tracking_confidence=0.5,
                output_face_blendshapes=False,
                output_facial_transformation_matrixes=False,
            )
            landmarker = mp.tasks.vision.FaceLandmarker.create_from_options(options)

            while not self._stop_event.is_set():
                try:
                    source_jpeg = self.camera_service.get_jpeg()
                    if not source_jpeg:
                        self._set_error("Camera has not supplied a frame yet")
                        self._stop_event.wait(0.05)
                        continue

                    # Some camera services may return a tuple; expect JPEG bytes
                    # in the first item if so.
                    if isinstance(source_jpeg, tuple):
                        source_jpeg = source_jpeg[0]

                    if not isinstance(source_jpeg, (bytes, bytearray, memoryview)):
                        self._set_error(
                            f"CameraService.get_jpeg() returned {type(source_jpeg).__name__}, expected JPEG bytes"
                        )
                        self._stop_event.wait(0.1)
                        continue

                    frame_array = np.frombuffer(source_jpeg, dtype=np.uint8)
                    frame = cv2.imdecode(frame_array, cv2.IMREAD_COLOR)
                    if frame is None:
                        self._set_error("Could not decode camera JPEG")
                        self._stop_event.wait(0.05)
                        continue

                    annotated = self._process_frame(frame, landmarker)
                    ok, encoded = cv2.imencode(
                        ".jpg", annotated, [int(cv2.IMWRITE_JPEG_QUALITY), 85]
                    )
                    if ok:
                        with self._lock:
                            self._last_frame_jpeg = encoded.tobytes()
                            self._last_frame_time = time.monotonic()
                            self._last_error = None

                    self._check_interval()
                except Exception as exc:
                    self._set_error(f"Frame processing error: {exc}")
                    if self._stop_event.wait(0.1):
                        break
        except Exception as exc:
            err_msg = f"Could not initialize MediaPipe Face Landmarker: {exc}"
            print(f"[BlinkCounter] {err_msg}")
            self._set_error(err_msg)
        finally:
            if landmarker is not None:
                try:
                    landmarker.close()
                except Exception:
                    pass

    def _process_frame(self, frame: np.ndarray, landmarker) -> np.ndarray:
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)

        # VIDEO mode requires strictly increasing millisecond timestamps.
        timestamp_ms = time.monotonic_ns() // 1_000_000
        if timestamp_ms <= self._last_timestamp_ms:
            timestamp_ms = self._last_timestamp_ms + 1
        self._last_timestamp_ms = timestamp_ms

        results = landmarker.detect_for_video(mp_image, timestamp_ms)
        height, width = frame.shape[:2]
        landmarks = results.face_landmarks[0] if results.face_landmarks else None

        with self._lock:
            self._face_detected = landmarks is not None

        if landmarks:
            left_ear = self._calculate_ear(landmarks, LEFT_EYE_INDICES, width, height)
            right_ear = self._calculate_ear(landmarks, RIGHT_EYE_INDICES, width, height)
            ear = (left_ear + right_ear) / 2.0

            self._update_blink_state(ear)

            with self._lock:
                self._last_ear = ear

            self._draw_eye_landmarks(frame, landmarks, width, height)
            cv2.putText(
                frame,
                f"EAR: {ear:.2f}",
                (10, height - 42),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.55,
                (80, 220, 255),
                2,
                cv2.LINE_AA,
            )
        else:
            with self._lock:
                self._last_ear = None
                self.closed_frames = 0
                self.eye_closed = False
            cv2.putText(
                frame,
                "Face not detected",
                (10, height - 42),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.55,
                (0, 180, 255),
                2,
                cv2.LINE_AA,
            )

        self._draw_counter_overlay(frame)
        return frame

    # ------------------------------------------------------------------
    # Blink detection / drawing
    # ------------------------------------------------------------------

    @staticmethod
    def _calculate_ear(landmarks, indices, width: int, height: int) -> float:
        points = np.array(
            [
                [landmarks[i].x * width, landmarks[i].y * height]
                for i in indices
            ],
            dtype=np.float32,
        )
        # EAR = (vertical distance 1 + vertical distance 2) / (2 * horizontal distance)
        vertical_1 = np.linalg.norm(points[1] - points[5])
        vertical_2 = np.linalg.norm(points[2] - points[4])
        horizontal = np.linalg.norm(points[0] - points[3])
        if horizontal < 1e-6:
            return 0.0
        return float((vertical_1 + vertical_2) / (2.0 * horizontal))

    def _update_blink_state(self, ear: float) -> None:
        with self._lock:
            if ear < self.ear_threshold:
                self.closed_frames += 1
                if self.closed_frames >= self.min_closed_frames:
                    self.eye_closed = True
            else:
                if self.eye_closed:
                    self.blink_count += 1
                    self.interval_blink_count += 1
                self.closed_frames = 0
                self.eye_closed = False

    @staticmethod
    def _draw_eye_landmarks(frame, landmarks, width: int, height: int) -> None:
        for indices in (LEFT_EYE_INDICES, RIGHT_EYE_INDICES):
            points = []
            for idx in indices:
                point = (
                    int(landmarks[idx].x * width),
                    int(landmarks[idx].y * height),
                )
                points.append(point)
                cv2.circle(frame, point, 2, (70, 255, 120), -1, cv2.LINE_AA)
            if len(points) >= 4:
                cv2.polylines(
                    frame,
                    [np.array(points, dtype=np.int32)],
                    isClosed=True,
                    color=(70, 255, 120),
                    thickness=1,
                    lineType=cv2.LINE_AA,
                )

    def _draw_counter_overlay(self, frame: np.ndarray) -> None:
        with self._lock:
            total = self.blink_count
            interval_count = self.interval_blink_count
            warning = self.last_interval_warning

        height, width = frame.shape[:2]
        box_width = min(250, max(180, width - 20))
        box_height = 78
        x1, y1 = 10, 10
        x2, y2 = min(width - 10, x1 + box_width), min(height - 10, y1 + box_height)

        overlay = frame.copy()
        cv2.rectangle(overlay, (x1, y1), (x2, y2), (12, 18, 32), -1)
        cv2.addWeighted(overlay, 0.78, frame, 0.22, 0, frame)

        color = (80, 190, 255) if warning else (100, 255, 160)
        cv2.putText(
            frame, f"Total blinks: {total}", (x1 + 10, y1 + 27),
            cv2.FONT_HERSHEY_SIMPLEX, 0.62, (255, 255, 255), 2, cv2.LINE_AA
        )
        cv2.putText(
            frame, f"This interval: {interval_count}", (x1 + 10, y1 + 53),
            cv2.FONT_HERSHEY_SIMPLEX, 0.52, color, 2, cv2.LINE_AA
        )

    def _check_interval(self) -> None:
        now = time.monotonic()
        with self._lock:
            elapsed = now - self.interval_start_time
            if elapsed < self.interval_seconds:
                return

            # If processing was delayed for multiple intervals, close the current
            # measured interval and advance the start to the latest interval edge.
            interval_count = self.interval_blink_count
            self.last_interval_count = interval_count
            self.last_interval_warning = interval_count < self.warning_threshold
            self.last_interval_end = time.time()
            intervals_elapsed = max(1, int(elapsed // self.interval_seconds))
            self.interval_start_time += intervals_elapsed * self.interval_seconds
            self.interval_blink_count = 0
            warning_triggered = self.last_interval_warning

        if warning_triggered:
            self._trigger_warning(interval_count)

    def _trigger_warning(self, count: int) -> None:
        print(
            f"[BlinkCounter] Blink warning triggered: {count} blinks in interval "
            f"(threshold: {self.warning_threshold})"
        )
        if self.notify_on_warning:
            if count == 0:
                sub = "Take a moment to rest and blink your eyes."
            else:
                sub = f"Only {count} blinks in the last minute (target: {self.warning_threshold})."
            send_mac_notification(
                message="Blink!",
                title="EyeDoc",
                subtitle=sub,
            )

        if self.on_warning:
            try:
                self.on_warning(count, self.warning_threshold)
            except Exception as exc:
                print(f"[BlinkCounter] on_warning callback error: {exc}")

    def trigger_test_warning(self) -> dict[str, Any]:
        """Manually trigger a warning notification for testing."""
        self._trigger_warning(0)
        return {
            "status": "warning_triggered",
            "message": "Blink!",
            "threshold": self.warning_threshold,
        }

    def _set_error(self, message: str) -> None:
        with self._lock:
            self._last_error = message


# Optional direct-run entry point for debugging only.
# In the desktop app, create BlinkCounterServer(camera_service=...) from app.py.
if __name__ == "__main__":
    raise SystemExit(
        "Run BlinkCounterServer from app.py with your existing CameraService."
    )
