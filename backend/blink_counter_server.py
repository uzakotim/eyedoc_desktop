"""
EyeDoc blink counter server.

Requires:
    pip install opencv-python mediapipe bottle cheroot

Model:
    backend/models/face_landmarker.task

The server reuses CameraService.get_jpeg(); it does not open a second camera.
"""

from __future__ import annotations

import math
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
    from notifications import (
        send_mac_notification,
        send_distance_notification,
        show_game_overlay,
    )
except ImportError:
    try:
        from backend.notifications import (
            send_mac_notification,
            send_distance_notification,
            show_game_overlay,
        )
    except ImportError:
        def send_mac_notification(message="Blink!", title="EyeDoc", **kwargs):
            pass
        def send_distance_notification(message="Move head farther from the screen", title="EyeDoc", **kwargs):
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
        depth_threshold: float = 0.4,
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
        self.depth_threshold = float(depth_threshold)
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

        # Distance estimation state (depth to eyes)
        self._last_distance: Optional[float] = None
        self._too_close_frames = 0
        self._distance_warning_active = False
        self._last_distance_warning_time = 0.0
        self.distance_warning_cooldown = 10.0  # seconds between warnings
        self.distance_consecutive_frames = 5   # consecutive frames < 0.4m before alert

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
                "distance": (
                    round(self._last_distance, 2)
                    if self._last_distance is not None
                    else None
                ),
                "distance_warning": self._distance_warning_active,
                "depth_threshold": self.depth_threshold,
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
            self._last_distance = None
            self._too_close_frames = 0
            self._distance_warning_active = False
        return {
            "reset": True,
            "blink_count": 0,
            "total_blinks": 0,
            "interval_blink_count": 0,
            "current_minute_blinks": 0,
            "last_interval_count": None,
            "last_interval_warning": False,
            "distance": None,
            "distance_warning": False,
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

        @self.app.route("/distance_notify_test", method=["GET", "POST", "OPTIONS"])
        def distance_notify_test_route():
            if self._is_options():
                return ""
            return self.trigger_test_distance_warning()

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

            # Calculate distance from camera to eyes based on face_landmarks and mediapipe
            raw_distance = self._calculate_eye_distance(landmarks, width, height)
            distance = self._update_distance_state(raw_distance)

            with self._lock:
                self._last_ear = ear

            is_too_close = distance is not None and distance < self.depth_threshold
            self._draw_eye_landmarks(frame, landmarks, width, height, is_too_close=is_too_close)

            cv2.putText(
                frame,
                f"EAR: {ear:.2f}",
                (10, height - 38),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.52,
                (80, 220, 255),
                2,
                cv2.LINE_AA,
            )

            # Distance display (red warning when < 0.4 meters)
            if distance is not None:
                dist_color = (60, 60, 255) if is_too_close else (100, 255, 160)
                dist_label = f"Dist: {distance:.2f}m" + (" (TOO CLOSE)" if is_too_close else "")
            else:
                dist_color = (180, 180, 180)
                dist_label = "Dist: --"

            cv2.putText(
                frame,
                dist_label,
                (10, height - 16),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.52,
                dist_color,
                2,
                cv2.LINE_AA,
            )
        else:
            with self._lock:
                self._last_ear = None
                self._last_distance = None
                self.closed_frames = 0
                self.eye_closed = False
                self._too_close_frames = 0
                self._distance_warning_active = False
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
    def _draw_eye_landmarks(frame, landmarks, width: int, height: int, is_too_close: bool = False) -> None:
        color = (60, 60, 255) if is_too_close else (70, 255, 120)
        for indices in (LEFT_EYE_INDICES, RIGHT_EYE_INDICES):
            points = []
            for idx in indices:
                point = (
                    int(landmarks[idx].x * width),
                    int(landmarks[idx].y * height),
                )
                points.append(point)
                cv2.circle(frame, point, 2, color, -1, cv2.LINE_AA)
            if len(points) >= 4:
                cv2.polylines(
                    frame,
                    [np.array(points, dtype=np.int32)],
                    isClosed=True,
                    color=color,
                    thickness=1,
                    lineType=cv2.LINE_AA,
                )

    @staticmethod
    def _calculate_eye_distance(landmarks, width: int, height: int) -> Optional[float]:
        """Calculate metric distance (in meters) from camera to eyes using face landmarks.

        Uses pinhole camera model with anthropometric human eye measurements:
        - Interpupillary distance (IPD) between eye centroids: ~63 mm (0.063 m)
        - Outer eye corners distance (exocanthion 33 to 263): ~96 mm (0.096 m)
        - Standard webcam horizontal FOV: ~65 degrees
        3D landmark coordinates (x, y, z) account for head yaw and pitch.
        """
        try:
            # Centroid of left eye
            lx = sum(landmarks[i].x for i in LEFT_EYE_INDICES) / len(LEFT_EYE_INDICES)
            ly = sum(landmarks[i].y for i in LEFT_EYE_INDICES) / len(LEFT_EYE_INDICES)
            lz = sum(landmarks[i].z for i in LEFT_EYE_INDICES) / len(LEFT_EYE_INDICES)

            # Centroid of right eye
            rx = sum(landmarks[i].x for i in RIGHT_EYE_INDICES) / len(RIGHT_EYE_INDICES)
            ry = sum(landmarks[i].y for i in RIGHT_EYE_INDICES) / len(RIGHT_EYE_INDICES)
            rz = sum(landmarks[i].z for i in RIGHT_EYE_INDICES) / len(RIGHT_EYE_INDICES)

            # 3D Euclidean distance between eye centroids in pixels
            dx = (rx - lx) * width
            dy = (ry - ly) * height
            dz = (rz - lz) * width
            d_eyes_px = math.sqrt(dx * dx + dy * dy + dz * dz)

            # 3D Euclidean distance between outer eye corners (33 and 263)
            dx_out = (landmarks[263].x - landmarks[33].x) * width
            dy_out = (landmarks[263].y - landmarks[33].y) * height
            dz_out = (landmarks[263].z - landmarks[33].z) * width
            d_outer_px = math.sqrt(dx_out * dx_out + dy_out * dy_out + dz_out * dz_out)

            # Camera focal length in pixels for ~65 deg HFOV webcam
            # fx = (width / 2) / tan(32.5 deg) ~= 0.7848 * width
            fx = width / (2.0 * math.tan(math.radians(32.5)))

            estimates = []
            if d_eyes_px > 1e-4:
                estimates.append((fx * 0.063) / d_eyes_px)
            if d_outer_px > 1e-4:
                estimates.append((fx * 0.096) / d_outer_px)

            if not estimates:
                return None

            return float(sum(estimates) / len(estimates))
        except Exception:
            return None

    def _update_distance_state(self, raw_distance: Optional[float]) -> Optional[float]:
        if raw_distance is None:
            return None

        # Clamp raw depth reading to reasonable desk bounds (0.1m - 3.0m)
        clamped = max(0.1, min(3.0, raw_distance))

        trigger_warning = False
        with self._lock:
            if self._last_distance is None:
                smooth_dist = clamped
            else:
                # Exponential moving average filter
                smooth_dist = 0.25 * clamped + 0.75 * self._last_distance
            self._last_distance = smooth_dist

            now = time.monotonic()
            if smooth_dist < self.depth_threshold:
                self._too_close_frames += 1
                if self._too_close_frames >= self.distance_consecutive_frames:
                    self._distance_warning_active = True
                    if (now - self._last_distance_warning_time) >= self.distance_warning_cooldown:
                        self._last_distance_warning_time = now
                        trigger_warning = True
            else:
                # Hysteresis buffer of 4cm to reset active alert state
                if smooth_dist >= (self.depth_threshold + 0.04):
                    self._too_close_frames = 0
                    self._distance_warning_active = False

        if trigger_warning:
            self._trigger_distance_warning(smooth_dist)

        return smooth_dist

    def _trigger_distance_warning(self, distance: Optional[float] = None) -> None:
        dist_str = f"{distance:.2f}m" if distance is not None else "< 0.4m"
        print(
            f"[BlinkCounter] Distance warning triggered: depth is {dist_str} "
            f"(threshold: {self.depth_threshold}m)"
        )
        if self.notify_on_warning:
            send_distance_notification(
                message="Move head farther",
                title="EyeDoc",
                subtitle=f"{dist_str} from the screen ,maintain at least 0.4m.",
                duration=3.8,
                sound=True,
                sound_name="Glass",
            )

    def trigger_test_distance_warning(self) -> dict[str, Any]:
        """Manually trigger a distance warning notification for testing."""
        self._trigger_distance_warning(0.35)
        return {
            "status": "distance_warning_triggered",
            "message": "Move head farther from the screen",
            "distance": 0.35,
            "threshold": self.depth_threshold,
        }

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
