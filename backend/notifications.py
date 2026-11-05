"""
macOS Notification helper for EyeDoc.

Provides in-game HUD overlay notifications that display on top of fullscreen
games and spaces without interrupting gameplay or stealing focus, combined
with audio chimes and native system notifications.
"""

from __future__ import annotations

import subprocess
import sys
import threading
from typing import Optional

try:
    import AppKit
    import Quartz
    from PyObjCTools import AppHelper
except ImportError:
    AppKit = None
    Quartz = None
    AppHelper = None


class MacGameOverlay:
    """Manages an on-screen HUD overlay notification window on macOS.

    Configured to float above full-screen games, video players, and apps
    without taking focus, interrupting mouse/keyboard inputs, or triggering
    macOS Game Mode / Focus suppression.
    """

    def __init__(self) -> None:
        self._panel: Optional[AppKit.NSPanel] = None
        self._hide_timer: Optional[threading.Timer] = None
        self._title_field: Optional[AppKit.NSTextField] = None
        self._subtitle_field: Optional[AppKit.NSTextField] = None
        self._effect_view: Optional[AppKit.NSVisualEffectView] = None
        self._icon_view: Optional[AppKit.NSImageView] = None
        self._lock = threading.Lock()

    def is_available(self) -> bool:
        return sys.platform == "darwin" and AppKit is not None and Quartz is not None

    def show(
        self,
        title: str = "EyeDoc",
        message: str = "Blink!",
        subtitle: str = "",
        duration: float = 3.8,
        sound: bool = True,
        color: str = "default",
        sound_name: Optional[str] = None,
    ) -> bool:
        if not self.is_available():
            return False

        if AppHelper is not None:
            AppHelper.callAfter(
                self._show_on_main_thread,
                title,
                message,
                subtitle,
                float(duration),
                bool(sound),
                str(color),
                sound_name,
            )
            return True

        return False

    def _play_sound(self, sound_name: Optional[str] = None) -> None:
        name = sound_name or "Ping"
        try:
            sound = AppKit.NSSound.soundNamed_(name)
            if sound:
                sound.play()
                return
        except Exception:
            pass

        # Fallback to system afplay
        try:
            subprocess.Popen(
                ["/usr/bin/afplay", f"/System/Library/Sounds/{name}.aiff"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except Exception:
            pass

    def _show_on_main_thread(
        self,
        title: str,
        message: str,
        subtitle: str,
        duration: float,
        sound: bool,
        color: str = "default",
        sound_name: Optional[str] = None,
    ) -> None:
        with self._lock:
            if self._hide_timer:
                self._hide_timer.cancel()
                self._hide_timer = None

            is_red = (color == "red")

            if sound:
                chosen_sound = sound_name or ("Glass" if is_red else "Ping")
                self._play_sound(chosen_sound)

            main_text = message
            sub_text = subtitle or ("Move head farther from the screen." if is_red else "Give your eyes a moment to rest and blink.")

            if is_red:
                # Glowing warning red colors
                border_color = AppKit.NSColor.colorWithCalibratedRed_green_blue_alpha_(
                    1.0, 0.28, 0.28, 0.88
                ).CGColor()
                bg_color = AppKit.NSColor.colorWithCalibratedRed_green_blue_alpha_(
                    0.16, 0.04, 0.06, 0.95
                ).CGColor()
                icon_color = AppKit.NSColor.colorWithCalibratedRed_green_blue_alpha_(
                    1.0, 0.35, 0.35, 1.0
                )
                sub_color = AppKit.NSColor.colorWithCalibratedRed_green_blue_alpha_(
                    1.0, 0.82, 0.85, 0.95
                )
            else:
                # Subtle glowing cyan / turquoise colors
                border_color = AppKit.NSColor.colorWithCalibratedRed_green_blue_alpha_(
                    0.3, 0.85, 0.95, 0.6
                ).CGColor()
                bg_color = AppKit.NSColor.colorWithCalibratedRed_green_blue_alpha_(
                    0.06, 0.08, 0.14, 0.94
                ).CGColor()
                icon_color = AppKit.NSColor.colorWithCalibratedRed_green_blue_alpha_(
                    0.35, 0.85, 1.0, 1.0
                )
                sub_color = AppKit.NSColor.colorWithCalibratedRed_green_blue_alpha_(
                    0.75, 0.88, 1.0, 0.95
                )

            # If panel is already active, refresh its content, style, and pulse visibility
            if self._panel is not None:
                try:
                    if self._title_field:
                        self._title_field.setStringValue_(f"{title} • {main_text}")
                    if self._subtitle_field:
                        self._subtitle_field.setStringValue_(sub_text)
                        self._subtitle_field.setTextColor_(sub_color)
                    if self._effect_view and self._effect_view.layer():
                        self._effect_view.layer().setBorderColor_(border_color)
                        self._effect_view.layer().setBackgroundColor_(bg_color)
                    if self._icon_view:
                        self._icon_view.setContentTintColor_(icon_color)

                    self._panel.setAlphaValue_(1.0)
                    self._panel.orderFrontRegardless()
                    self._schedule_hide(duration)
                    return
                except Exception:
                    self._cleanup_panel()

            # Construct new HUD overlay panel
            try:
                screen = AppKit.NSScreen.mainScreen()
                s_frame = screen.frame() if screen else AppKit.NSMakeRect(0, 0, 1440, 900)

                w = 400.0
                h = 76.0
                x = s_frame.origin.x + (s_frame.size.width - w) / 2.0
                # 44px below top edge of screen
                y = s_frame.origin.y + s_frame.size.height - h - 44.0

                frame = AppKit.NSMakeRect(x, y, w, h)
                panel = AppKit.NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
                    frame,
                    AppKit.NSWindowStyleMaskBorderless
                    | AppKit.NSWindowStyleMaskNonactivatingPanel,
                    AppKit.NSBackingStoreBuffered,
                    False,
                )

                # Shielding window level guarantees visibility above full-screen games
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
                # Ignore mouse events so user can click through during gaming
                panel.setIgnoresMouseEvents_(True)
                panel.setHidesOnDeactivate_(False)

                content = panel.contentView()
                content.setWantsLayer_(True)

                # Frosted glass background
                effect_view = AppKit.NSVisualEffectView.alloc().initWithFrame_(
                    AppKit.NSMakeRect(0, 0, w, h)
                )
                effect_view.setMaterial_(AppKit.NSVisualEffectMaterialHUDWindow)
                effect_view.setBlendingMode_(
                    AppKit.NSVisualEffectBlendingModeBehindWindow
                )
                effect_view.setState_(AppKit.NSVisualEffectStateActive)
                effect_view.setWantsLayer_(True)

                layer = effect_view.layer()
                layer.setCornerRadius_(22.0)
                layer.setMasksToBounds_(True)
                layer.setBorderWidth_(1.5)
                layer.setBorderColor_(border_color)
                layer.setBackgroundColor_(bg_color)

                content.addSubview_(effect_view)
                self._effect_view = effect_view

                # Icon: eye.fill SF Symbol matching the app icon
                img = AppKit.NSImage.imageWithSystemSymbolName_accessibilityDescription_(
                    "eye.fill", "EyeDoc"
                )
                if img:
                    try:
                        config = AppKit.NSImageSymbolConfiguration.configurationWithPointSize_weight_(
                            26, AppKit.NSFontWeightSemibold
                        )
                        if config:
                            img = img.imageWithSymbolConfiguration_(config)
                    except Exception:
                        pass

                    icon_view = AppKit.NSImageView.alloc().initWithFrame_(
                        AppKit.NSMakeRect(18, (h - 38) / 2.0, 38, 38)
                    )
                    icon_view.setImage_(img)
                    icon_view.setImageScaling_(AppKit.NSImageScaleProportionallyUpOrDown)
                    icon_view.setContentTintColor_(icon_color)
                    effect_view.addSubview_(icon_view)
                    self._icon_view = icon_view
                else:
                    # Fallback if SF Symbols are not available
                    icon_field = AppKit.NSTextField.alloc().initWithFrame_(
                        AppKit.NSMakeRect(18, (h - 38) / 2.0, 38, 38)
                    )
                    icon_field.setEditable_(False)
                    icon_field.setSelectable_(False)
                    icon_field.setBezeled_(False)
                    icon_field.setDrawsBackground_(False)
                    icon_field.setStringValue_("👁")
                    icon_field.setFont_(AppKit.NSFont.systemFontOfSize_(26))
                    effect_view.addSubview_(icon_field)

                # Title text
                title_field = AppKit.NSTextField.alloc().initWithFrame_(
                    AppKit.NSMakeRect(68, 38, w - 86, 24)
                )
                title_field.setEditable_(False)
                title_field.setSelectable_(False)
                title_field.setBezeled_(False)
                title_field.setDrawsBackground_(False)
                title_field.setStringValue_(f"{title} • {main_text}")
                title_field.setFont_(AppKit.NSFont.boldSystemFontOfSize_(15))
                title_field.setTextColor_(AppKit.NSColor.whiteColor())
                effect_view.addSubview_(title_field)
                self._title_field = title_field

                # Subtitle text
                subtitle_field = AppKit.NSTextField.alloc().initWithFrame_(
                    AppKit.NSMakeRect(68, 14, w - 86, 22)
                )
                subtitle_field.setEditable_(False)
                subtitle_field.setSelectable_(False)
                subtitle_field.setBezeled_(False)
                subtitle_field.setDrawsBackground_(False)
                subtitle_field.setStringValue_(sub_text)
                subtitle_field.setFont_(AppKit.NSFont.systemFontOfSize_(12))
                subtitle_field.setTextColor_(sub_color)
                effect_view.addSubview_(subtitle_field)
                self._subtitle_field = subtitle_field

                self._panel = panel

                # Smooth fade in
                panel.setAlphaValue_(0.0)
                panel.orderFrontRegardless()

                AppKit.NSAnimationContext.beginGrouping()
                AppKit.NSAnimationContext.currentContext().setDuration_(0.22)
                panel.animator().setAlphaValue_(1.0)
                AppKit.NSAnimationContext.endGrouping()

                self._schedule_hide(duration)
            except Exception as exc:
                print(f"[Notifications] Error displaying HUD overlay: {exc}")
                self._cleanup_panel()

    def _schedule_hide(self, delay: float) -> None:
        def _trigger_fade_out():
            if AppHelper is not None:
                AppHelper.callAfter(self._fade_out_on_main_thread)

        self._hide_timer = threading.Timer(delay, _trigger_fade_out)
        self._hide_timer.daemon = True
        self._hide_timer.start()

    def _fade_out_on_main_thread(self) -> None:
        with self._lock:
            panel = self._panel
            if panel is None:
                return

            def _on_complete():
                with self._lock:
                    self._cleanup_panel()

            try:
                AppKit.NSAnimationContext.beginGrouping()
                AppKit.NSAnimationContext.currentContext().setDuration_(0.4)
                AppKit.NSAnimationContext.currentContext().setCompletionHandler_(
                    _on_complete
                )
                panel.animator().setAlphaValue_(0.0)
                AppKit.NSAnimationContext.endGrouping()
            except Exception:
                self._cleanup_panel()

    def _cleanup_panel(self) -> None:
        if self._panel is not None:
            try:
                self._panel.orderOut_(None)
                self._panel.close()
            except Exception:
                pass
            self._panel = None
        self._title_field = None
        self._subtitle_field = None
        self._effect_view = None
        self._icon_view = None

    def close(self) -> None:
        with self._lock:
            if self._hide_timer:
                self._hide_timer.cancel()
                self._hide_timer = None
            if AppHelper is not None:
                AppHelper.callAfter(self._cleanup_panel)
            else:
                self._cleanup_panel()


# Global overlay singleton
_overlay_manager = MacGameOverlay()


def show_game_overlay(
    message: str = "Blink!",
    title: str = "EyeDoc",
    subtitle: str = "",
    duration: float = 3.8,
    sound: bool = True,
    color: str = "default",
    sound_name: Optional[str] = None,
) -> bool:
    """Display an on-screen HUD overlay notification visible even during games."""
    return _overlay_manager.show(
        title=title,
        message=message,
        subtitle=subtitle,
        duration=duration,
        sound=sound,
        color=color,
        sound_name=sound_name,
    )


def cleanup_notifications() -> None:
    """Close any active notification panels on app shutdown."""
    _overlay_manager.close()


def send_mac_notification(
    message: str = "Blink!",
    title: str = "EyeDoc",
    subtitle: str = "",
    sound: bool = True,
    duration: float = 3.8,
    color: str = "default",
    sound_name: Optional[str] = None,
) -> bool:
    """Send on-screen HUD overlay notification with the eye icon."""
    if sys.platform != "darwin":
        return False

    return show_game_overlay(
        message=message,
        title=title,
        subtitle=subtitle,
        duration=duration,
        sound=sound,
        color=color,
        sound_name=sound_name,
    )


def send_distance_notification(
    message: str = "Move head farther",
    title: str = "EyeDoc",
    subtitle: str = "Your eyes are closer than 0.4m from the screen.",
    sound: bool = True,
    duration: float = 3.8,
    sound_name: str = "Glass",
) -> bool:
    """Send distance warning HUD overlay notification in red with an alert sound."""
    return send_mac_notification(
        message=message,
        title=title,
        subtitle=subtitle,
        sound=sound,
        duration=duration,
        color="red",
        sound_name=sound_name,
    )
