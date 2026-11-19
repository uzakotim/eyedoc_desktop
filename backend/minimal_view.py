"""
EyeDoc Minimal Circle View Overlay – cross-platform.

macOS  – Floating NSPanel HUD circle (AppKit / PyObjC) that sits above
         full-screen games and spaces, draggable, no focus steal.
Windows – Lightweight tkinter frameless window that stays on top,
          draggable, transparent background via color-key attribute.
"""

from __future__ import annotations

import sys
import threading
from typing import Any, Callable, Optional

# ---------------------------------------------------------------------------
# macOS-only imports
# ---------------------------------------------------------------------------
try:
    import AppKit
    import Quartz
    import objc
    from PyObjCTools import AppHelper
except ImportError:
    AppKit = None
    Quartz = None
    objc = None
    AppHelper = None

# ---------------------------------------------------------------------------
# macOS draggable NSView class (only defined when AppKit is present)
# ---------------------------------------------------------------------------
if AppKit is not None and objc is not None:
    try:
        EyeDocMinimalCircleView = objc.lookUpClass("EyeDocMinimalCircleView")
    except objc.nosuchclass_error:
        class EyeDocMinimalCircleView(AppKit.NSView):
            def initWithFrame_overlay_(self, frame, overlay):
                self = objc.super(EyeDocMinimalCircleView, self).initWithFrame_(frame)
                if self:
                    self._overlay = overlay
                    self._initial_pos = None
                    self._is_dragging = False
                return self

            def acceptsFirstMouse_(self, event):
                return True

            def mouseDown_(self, event):
                self._initial_pos = event.locationInWindow()
                self._is_dragging = False

            def mouseDragged_(self, event):
                win = self.window()
                if not win or self._initial_pos is None:
                    return
                self._is_dragging = True
                loc = event.locationInWindow()
                frame = win.frame()
                new_x = frame.origin.x + (loc.x - self._initial_pos.x)
                new_y = frame.origin.y + (loc.y - self._initial_pos.y)
                win.setFrameOrigin_(AppKit.NSMakePoint(new_x, new_y))
                if self._overlay:
                    self._overlay.remember_position(new_x, new_y)

            def mouseUp_(self, event):
                if not self._is_dragging and event.clickCount() == 2:
                    if self._overlay and self._overlay.on_open_main_app:
                        self._overlay.on_open_main_app()
                self._is_dragging = False

            def rightMouseUp_(self, event):
                menu = AppKit.NSMenu.alloc().init()

                item_hide = AppKit.NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
                    "Hide Minimal View", "onHideMinimal:", ""
                )
                item_hide.setTarget_(self)
                menu.addItem_(item_hide)

                item_app = AppKit.NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
                    "Open EyeDoc Window", "onOpenApp:", ""
                )
                item_app.setTarget_(self)
                menu.addItem_(item_app)

                AppKit.NSMenu.popUpContextMenu_withEvent_forView_(menu, event, self)

            @objc.IBAction
            def onHideMinimal_(self, sender):
                if self._overlay:
                    self._overlay.hide()

            @objc.IBAction
            def onOpenApp_(self, sender):
                if self._overlay and self._overlay.on_open_main_app:
                    self._overlay.on_open_main_app()

    DraggableCircleView = EyeDocMinimalCircleView
else:
    DraggableCircleView = None


# ---------------------------------------------------------------------------
# Windows tkinter overlay helper
# ---------------------------------------------------------------------------

class _WinMinimalOverlay:
    """Lightweight always-on-top tkinter circle overlay for Windows."""

    SIZE = 62
    TRANSPARENT_KEY = "#ff00fe"
    FILL_NORMAL = "#0f1424"
    FILL_WARNING = "#290a0e"
    BORDER_NORMAL = "#4dd9f5"
    BORDER_PULSE = "#8cecff"
    BORDER_WARNING = "#f54040"
    TEXT_NORMAL = "#eaf8ff"
    TEXT_WARNING = "#ffd6d6"

    def __init__(self, blink_server=None, on_open_main_app: Optional[Callable] = None) -> None:
        self.blink_server = blink_server
        self.on_open_main_app = on_open_main_app

        self._visible = False
        self._lock = threading.RLock()
        self._tk_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._root = None
        self._canvas = None
        self._text_id = None
        self._last_position: Optional[tuple[int, int]] = None
        self._drag_start: Optional[tuple[int, int]] = None
        self._pulse_timer: Optional[threading.Timer] = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def is_available(self) -> bool:
        return sys.platform == "win32"

    def is_visible(self) -> bool:
        with self._lock:
            return self._visible

    def toggle(self) -> dict[str, bool]:
        with self._lock:
            if self._visible:
                self.hide()
                return {"visible": False}
            self.show()
            return {"visible": True}

    def show(self) -> bool:
        if not self.is_available():
            return False
        with self._lock:
            self._visible = True
        self._ensure_tk_thread()
        return True

    def hide(self) -> bool:
        with self._lock:
            self._visible = False
            root = self._root
        if root is not None:
            try:
                root.after(0, root.withdraw)
            except Exception:
                pass
        return True

    def remember_position(self, x: float, y: float) -> None:
        with self._lock:
            self._last_position = (int(x), int(y))

    def on_blink(self, count: Optional[int] = None) -> None:
        with self._lock:
            if not self._visible:
                return
            root = self._root
            canvas = self._canvas
        if root is not None and canvas is not None:
            try:
                root.after(0, lambda: self._pulse_on_tk(root, canvas, count))
            except Exception:
                pass

    def close(self) -> None:
        self._stop_event.set()
        with self._lock:
            self._visible = False
            root = self._root
            if self._pulse_timer is not None:
                self._pulse_timer.cancel()
                self._pulse_timer = None
        if root is not None:
            try:
                root.after(0, root.destroy)
            except Exception:
                pass

    # ------------------------------------------------------------------
    # tkinter thread
    # ------------------------------------------------------------------

    def _ensure_tk_thread(self) -> None:
        with self._lock:
            thread = self._tk_thread
            root = self._root

        if thread is not None and thread.is_alive():
            if root is not None:
                try:
                    root.after(0, self._show_window_on_tk)
                except Exception:
                    pass
            return

        self._stop_event.clear()
        new_thread = threading.Thread(
            target=self._run_tk,
            name="MinimalOverlayTk",
            daemon=True,
        )
        with self._lock:
            self._tk_thread = new_thread
        new_thread.start()

    def _show_window_on_tk(self) -> None:
        with self._lock:
            root = self._root
            visible = self._visible
        if root is not None and visible:
            root.deiconify()
            root.lift()
            root.attributes("-topmost", True)

    def _pulse_on_tk(self, root, canvas, count: Optional[int]) -> None:
        if self._stop_event.is_set() or not self._visible:
            return
        try:
            if count is not None and self._text_id is not None:
                canvas.itemconfig(self._text_id, text=str(count))

            current_outline = canvas.itemcget("border", "outline")
            if current_outline != self.BORDER_WARNING:
                canvas.itemconfig("border", outline=self.BORDER_PULSE)

                with self._lock:
                    if self._pulse_timer is not None:
                        self._pulse_timer.cancel()

                    def _restore() -> None:
                        if self._stop_event.is_set():
                            return
                        try:
                            root.after(0, lambda: canvas.itemconfig("border", outline=self.BORDER_NORMAL))
                        except Exception:
                            pass

                    timer = threading.Timer(0.18, _restore)
                    timer.daemon = True
                    self._pulse_timer = timer
                    timer.start()
        except Exception:
            pass

    def _run_tk(self) -> None:
        root = None
        try:
            import tkinter as tk

            root = tk.Tk()
            size = int(self.SIZE)

            with self._lock:
                pos = self._last_position

            if pos is None:
                sw = root.winfo_screenwidth()
                x = max(20, sw - size - 28)
                y = 50
                pos = (x, y)
                with self._lock:
                    self._last_position = pos

            root.overrideredirect(True)
            root.attributes("-topmost", True)
            root.title("EyeDoc")
            root.configure(bg=self.TRANSPARENT_KEY)
            root.geometry(f"{size}x{size}+{pos[0]}+{pos[1]}")

            transparent_active = False
            try:
                root.wm_attributes("-transparentcolor", self.TRANSPARENT_KEY)
                transparent_active = True
            except tk.TclError:
                pass

            canvas_bg = self.TRANSPARENT_KEY if transparent_active else self.FILL_NORMAL

            canvas = tk.Canvas(
                root,
                width=size,
                height=size,
                bg=canvas_bg,
                highlightthickness=0,
                bd=0,
            )
            canvas.pack(fill="both", expand=True)

            pad = 2
            center = size / 2.0
            canvas.create_oval(
                pad,
                pad,
                size - pad,
                size - pad,
                fill=self.FILL_NORMAL,
                outline=self.BORDER_NORMAL,
                width=2,
                tags="border",
            )

            text_id = canvas.create_text(
                center,
                center,
                text="0",
                fill=self.TEXT_NORMAL,
                font=("Consolas", 18, "bold"),
                tags="label",
            )

            with self._lock:
                self._root = root
                self._canvas = canvas
                self._text_id = text_id

            def on_mouse_down(event) -> None:
                self._drag_start = (
                    event.x_root - root.winfo_x(),
                    event.y_root - root.winfo_y(),
                )

            def on_mouse_drag(event) -> None:
                if self._drag_start is None:
                    return
                nx = event.x_root - self._drag_start[0]
                ny = event.y_root - self._drag_start[1]
                root.geometry(f"+{nx}+{ny}")
                self.remember_position(nx, ny)

            def on_double_click(_event) -> None:
                cb = self.on_open_main_app
                if cb:
                    threading.Thread(target=cb, daemon=True).start()

            def on_right_click(event) -> None:
                menu = tk.Menu(root, tearoff=0)
                menu.add_command(label="Hide Minimal View", command=self.hide)
                cb = self.on_open_main_app
                if cb:
                    menu.add_command(
                        label="Open EyeDoc Window",
                        command=lambda: threading.Thread(target=cb, daemon=True).start(),
                    )
                try:
                    menu.tk_popup(event.x_root, event.y_root)
                finally:
                    try:
                        menu.grab_release()
                    except Exception:
                        pass

            canvas.tag_bind("border", "<ButtonPress-1>", on_mouse_down)
            canvas.tag_bind("border", "<B1-Motion>", on_mouse_drag)
            canvas.tag_bind("border", "<Double-Button-1>", on_double_click)
            canvas.tag_bind("border", "<Button-3>", on_right_click)

            canvas.tag_bind("label", "<ButtonPress-1>", on_mouse_down)
            canvas.tag_bind("label", "<B1-Motion>", on_mouse_drag)
            canvas.tag_bind("label", "<Double-Button-1>", on_double_click)
            canvas.tag_bind("label", "<Button-3>", on_right_click)

            def _poll() -> None:
                if self._stop_event.is_set():
                    try:
                        root.destroy()
                    except Exception:
                        pass
                    return

                with self._lock:
                    visible = self._visible

                if not visible:
                    root.withdraw()
                else:
                    if not root.winfo_viewable():
                        root.deiconify()
                        root.lift()

                    count = 0
                    warning = False
                    face = True
                    if self.blink_server is not None:
                        try:
                            status = self.blink_server.get_status()
                            count = status.get("interval_blink_count", 0)
                            warning = bool(status.get("last_interval_warning", False))
                            face = bool(status.get("face_detected", False))
                        except Exception:
                            pass

                    display_str = str(count) if face else "–"
                    if warning:
                        fill_col = self.FILL_WARNING
                        border_col = self.BORDER_WARNING
                        text_col = self.TEXT_WARNING
                    else:
                        fill_col = self.FILL_NORMAL
                        border_col = self.BORDER_NORMAL
                        text_col = self.TEXT_NORMAL

                    try:
                        canvas.itemconfig(text_id, text=display_str, fill=text_col)
                        canvas.itemconfig("border", fill=fill_col, outline=border_col)
                    except Exception:
                        pass

                root.after(350, _poll)

            root.after(50, _poll)
            root.mainloop()
        except Exception as exc:
            print(f"[MinimalOverlay/Win] tkinter thread error: {exc}")
        finally:
            with self._lock:
                self._root = None
                self._canvas = None
                self._text_id = None
                self._tk_thread = None
                if self._pulse_timer is not None:
                    self._pulse_timer.cancel()
                    self._pulse_timer = None
            if root is not None:
                try:
                    root.destroy()
                except Exception:
                    pass


# ---------------------------------------------------------------------------
# macOS implementation
# ---------------------------------------------------------------------------

class _MacMinimalOverlay:
    """Manages an always-on-top circular HUD overlay window on macOS."""

    def __init__(self, blink_server=None, on_open_main_app: Optional[Callable] = None) -> None:
        self.blink_server = blink_server
        self.on_open_main_app = on_open_main_app
        self._panel = None
        self._effect_view = None
        self._label = None
        self._visible = False
        self._last_position: Optional[tuple[float, float]] = None
        self._lock = threading.RLock()
        self._poll_thread: Optional[threading.Thread] = None
        self._stop_poll = threading.Event()
        self._last_count: Optional[int] = None
        self._last_warning: Optional[bool] = None
        self._last_face: Optional[bool] = None

    def is_available(self) -> bool:
        return sys.platform == "darwin" and AppKit is not None and Quartz is not None

    def is_visible(self) -> bool:
        with self._lock:
            return self._visible

    def toggle(self) -> dict[str, bool]:
        with self._lock:
            if self._visible:
                self.hide()
                return {"visible": False}
            self.show()
            return {"visible": True}

    def show(self) -> bool:
        if not self.is_available():
            return False
        with self._lock:
            self._visible = True
        if AppHelper is not None:
            AppHelper.callAfter(self._show_on_main_thread)
        self._start_polling()
        return True

    def hide(self) -> bool:
        with self._lock:
            self._visible = False
        if AppHelper is not None:
            AppHelper.callAfter(self._hide_on_main_thread)
        self._stop_polling()
        return True

    def remember_position(self, x: float, y: float) -> None:
        with self._lock:
            self._last_position = (x, y)

    def on_blink(self, count: Optional[int] = None) -> None:
        if not self._visible or AppHelper is None:
            return
        AppHelper.callAfter(self._on_blink_main_thread)

    def close(self) -> None:
        self.hide()
        if AppHelper is not None:
            def _destroy():
                if self._panel:
                    try:
                        self._panel.close()
                    except Exception:
                        pass
                    self._panel = None
            AppHelper.callAfter(_destroy)

    # ------------------------------------------------------------------

    def _show_on_main_thread(self) -> None:
        try:
            if self._panel is None:
                self._build_panel()
            if self._panel is not None:
                if self._last_position:
                    self._panel.setFrameOrigin_(
                        AppKit.NSMakePoint(self._last_position[0], self._last_position[1])
                    )
                self._panel.setAlphaValue_(1.0)
                self._panel.orderFrontRegardless()
                self._update_display(force=True)
        except Exception as exc:
            print(f"[MinimalOverlay] Error displaying overlay: {exc}")

    def _hide_on_main_thread(self) -> None:
        try:
            if self._panel is not None:
                self._panel.orderOut_(None)
        except Exception as exc:
            print(f"[MinimalOverlay] Error hiding overlay: {exc}")

    def _build_panel(self) -> None:
        size = 62.0
        screen = AppKit.NSScreen.mainScreen()
        s_frame = screen.frame() if screen else AppKit.NSMakeRect(0, 0, 1440, 900)

        if not self._last_position:
            x = s_frame.origin.x + s_frame.size.width - size - 28.0
            y = s_frame.origin.y + s_frame.size.height - size - 50.0
            self._last_position = (x, y)
        else:
            x, y = self._last_position

        frame = AppKit.NSMakeRect(x, y, size, size)

        panel = AppKit.NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            frame,
            AppKit.NSWindowStyleMaskBorderless | AppKit.NSWindowStyleMaskNonactivatingPanel,
            AppKit.NSBackingStoreBuffered,
            False,
        )

        panel.setLevel_(Quartz.CGShieldingWindowLevel())
        panel.setCollectionBehavior_(
            AppKit.NSWindowCollectionBehaviorCanJoinAllSpaces
            | AppKit.NSWindowCollectionBehaviorFullScreenAuxiliary
            | AppKit.NSWindowCollectionBehaviorStationary
            | AppKit.NSWindowCollectionBehaviorIgnoresCycle
        )
        panel.setOpaque_(False)
        panel.setBackgroundColor_(AppKit.NSColor.clearColor())
        panel.setHasShadow_(True)
        panel.setIgnoresMouseEvents_(False)
        panel.setHidesOnDeactivate_(False)

        content = DraggableCircleView.alloc().initWithFrame_overlay_(
            AppKit.NSMakeRect(0, 0, size, size),
            self,
        )
        content.setWantsLayer_(True)
        content.setToolTip_("EyeDoc — Blinks this minute (drag to move, right-click to close)")

        effect_view = AppKit.NSVisualEffectView.alloc().initWithFrame_(
            AppKit.NSMakeRect(0, 0, size, size)
        )
        effect_view.setMaterial_(AppKit.NSVisualEffectMaterialHUDWindow)
        effect_view.setBlendingMode_(AppKit.NSVisualEffectBlendingModeBehindWindow)
        effect_view.setState_(AppKit.NSVisualEffectStateActive)
        effect_view.setWantsLayer_(True)

        layer = effect_view.layer()
        layer.setCornerRadius_(size / 2.0)
        layer.setMasksToBounds_(True)
        layer.setBorderWidth_(1.5)

        border_color = AppKit.NSColor.colorWithCalibratedRed_green_blue_alpha_(
            0.3, 0.85, 0.95, 0.65
        ).CGColor()
        bg_color = AppKit.NSColor.colorWithCalibratedRed_green_blue_alpha_(
            0.06, 0.08, 0.14, 0.94
        ).CGColor()
        layer.setBorderColor_(border_color)
        layer.setBackgroundColor_(bg_color)

        content.addSubview_(effect_view)
        self._effect_view = effect_view

        label = AppKit.NSTextField.alloc().initWithFrame_(
            AppKit.NSMakeRect(0, (size - 30) / 2.0 - 1.0, size, 30)
        )
        label.setEditable_(False)
        label.setSelectable_(False)
        label.setBezeled_(False)
        label.setDrawsBackground_(False)
        label.setAlignment_(AppKit.NSTextAlignmentCenter)
        label.setFont_(AppKit.NSFont.monospacedDigitSystemFontOfSize_weight_(23, AppKit.NSFontWeightBold))
        label.setStringValue_("0")
        label.setTextColor_(
            AppKit.NSColor.colorWithCalibratedRed_green_blue_alpha_(0.92, 0.97, 1.0, 1.0)
        )

        content.addSubview_(label)
        self._label = label

        panel.setContentView_(content)
        self._panel = panel

    def _update_display(self, force: bool = False) -> None:
        try:
            if not self._panel or not self._visible:
                return

            count = 0
            face_detected = True
            warning = False

            if self.blink_server:
                try:
                    s = self.blink_server.get_status()
                    count = s.get("interval_blink_count", 0)
                    face_detected = s.get("face_detected", False)
                    warning = s.get("last_interval_warning", False)
                except Exception:
                    pass

            if not force and count == self._last_count and warning == self._last_warning and face_detected == self._last_face:
                return

            self._last_count = count
            self._last_warning = warning
            self._last_face = face_detected

            if self._label:
                val_str = str(count) if face_detected else "–"
                self._label.setStringValue_(val_str)
                if warning:
                    self._label.setTextColor_(
                        AppKit.NSColor.colorWithCalibratedRed_green_blue_alpha_(1.0, 0.82, 0.85, 1.0)
                    )
                else:
                    self._label.setTextColor_(
                        AppKit.NSColor.colorWithCalibratedRed_green_blue_alpha_(0.92, 0.97, 1.0, 1.0)
                    )

            if self._effect_view and self._effect_view.layer():
                layer = self._effect_view.layer()
                if warning:
                    border_color = AppKit.NSColor.colorWithCalibratedRed_green_blue_alpha_(
                        1.0, 0.28, 0.28, 0.88
                    ).CGColor()
                    bg_color = AppKit.NSColor.colorWithCalibratedRed_green_blue_alpha_(
                        0.16, 0.04, 0.06, 0.95
                    ).CGColor()
                else:
                    border_color = AppKit.NSColor.colorWithCalibratedRed_green_blue_alpha_(
                        0.3, 0.85, 0.95, 0.65
                    ).CGColor()
                    bg_color = AppKit.NSColor.colorWithCalibratedRed_green_blue_alpha_(
                        0.06, 0.08, 0.14, 0.94
                    ).CGColor()
                layer.setBorderColor_(border_color)
                layer.setBackgroundColor_(bg_color)
        except Exception as exc:
            print(f"[MinimalOverlay] Error updating display: {exc}")

    def _on_blink_main_thread(self) -> None:
        try:
            if not self._visible or not self._panel:
                return
            self._update_display(force=True)

            if self._effect_view and self._effect_view.layer() and not self._last_warning:
                layer = self._effect_view.layer()
                pulse_border = AppKit.NSColor.colorWithCalibratedRed_green_blue_alpha_(
                    0.55, 0.95, 1.0, 0.98
                ).CGColor()
                normal_border = AppKit.NSColor.colorWithCalibratedRed_green_blue_alpha_(
                    0.3, 0.85, 0.95, 0.65
                ).CGColor()
                layer.setBorderColor_(pulse_border)

                def _revert():
                    if self._effect_view and self._effect_view.layer() and not self._last_warning:
                        self._effect_view.layer().setBorderColor_(normal_border)

                threading.Timer(0.18, lambda: AppHelper.callAfter(_revert)).start()
        except Exception as exc:
            print(f"[MinimalOverlay] Error during blink pulse: {exc}")

    def _start_polling(self) -> None:
        self._stop_polling()
        self._stop_poll.clear()

        def _run():
            while not self._stop_poll.is_set():
                if self._visible and AppHelper is not None:
                    AppHelper.callAfter(self._update_display)
                self._stop_poll.wait(0.35)

        self._poll_thread = threading.Thread(target=_run, name="MinimalOverlayPoll", daemon=True)
        self._poll_thread.start()

    def _stop_polling(self) -> None:
        self._stop_poll.set()
        self._poll_thread = None


# ---------------------------------------------------------------------------
# Null implementation (Linux / unsupported platforms)
# ---------------------------------------------------------------------------

class _NullMinimalOverlay:
    def is_available(self) -> bool:
        return False

    def is_visible(self) -> bool:
        return False

    def toggle(self) -> dict[str, bool]:
        return {"visible": False}

    def show(self) -> bool:
        return False

    def hide(self) -> bool:
        return False

    def remember_position(self, x: float, y: float) -> None:
        pass

    def on_blink(self, count: Optional[int] = None) -> None:
        pass

    def close(self) -> None:
        pass


# ---------------------------------------------------------------------------
# Unified public class
# ---------------------------------------------------------------------------

class MinimalCircleOverlay:
    """Cross-platform minimal blink-count circle overlay.

    On macOS uses NSPanel; on Windows uses a tkinter frameless window.
    """

    def __init__(self, blink_server=None, on_open_main_app: Optional[Callable] = None) -> None:
        self.blink_server = blink_server
        self.on_open_main_app = on_open_main_app

        if sys.platform == "darwin":
            self._impl: Any = _MacMinimalOverlay(blink_server, on_open_main_app)
        elif sys.platform == "win32":
            self._impl = _WinMinimalOverlay(blink_server, on_open_main_app)
        else:
            self._impl = _NullMinimalOverlay()

    def is_available(self) -> bool:
        return self._impl.is_available()

    def is_visible(self) -> bool:
        return self._impl.is_visible()

    def toggle(self) -> dict[str, bool]:
        return self._impl.toggle()

    def show(self) -> bool:
        return self._impl.show()

    def hide(self) -> bool:
        return self._impl.hide()

    def remember_position(self, x: float, y: float) -> None:
        self._impl.remember_position(x, y)

    def on_blink(self, count: Optional[int] = None) -> None:
        self._impl.on_blink(count)

    def close(self) -> None:
        self._impl.close()
