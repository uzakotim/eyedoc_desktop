"""
EyeDoc Minimal Circle View Overlay.

A floating, circular HUD overlay that displays the blink count for the current
minute. Configured with a glowing cyan / warning-red border matching EyeDoc
notifications, staying in front of all applications (including full-screen games
and spaces), and draggable anywhere on the screen.
"""

from __future__ import annotations

import sys
import threading
from typing import Any, Callable, Optional

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


class MinimalCircleOverlay:
    """Manages an always-on-top circular HUD overlay window on macOS."""

    def __init__(self, blink_server=None, on_open_main_app: Optional[Callable] = None) -> None:
        self.blink_server = blink_server
        self.on_open_main_app = on_open_main_app
        self._panel: Optional[AppKit.NSPanel] = None
        self._effect_view: Optional[AppKit.NSVisualEffectView] = None
        self._label: Optional[AppKit.NSTextField] = None
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
            else:
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
        """Triggered immediately when a blink occurs."""
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
    # Internal Main-Thread Logic
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
            # Default to top-right of main screen, below macOS menubar
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

        # Shielding window level guarantees visibility above full-screen games & any other app
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

        # Frosted glass background matching EyeDoc HUD notifications
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

        # Notification-style cyan glowing border & dark frosted background
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

        # Number label inside circle
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

            # Update text
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

            # Update border and background (cyan vs warning red)
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

            # Subtle flash pulse on blink
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
