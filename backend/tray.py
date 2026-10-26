import os
import sys
import threading
import webview
from PIL import Image, ImageDraw

def create_default_tray_image():
    """Generates an eye/camera icon image for tray on Windows/Linux."""
    size = 64
    image = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)

    # Outer eye outline
    draw.ellipse([6, 16, 58, 48], outline=(255, 255, 255, 230), width=4)
    # Pupil iris
    draw.ellipse([22, 22, 42, 42], fill=(139, 92, 246, 255))
    # Inner light pupil
    draw.ellipse([28, 28, 36, 36], fill=(255, 255, 255, 255))
    return image

class SystemTrayManager:
    def __init__(self, on_toggle, on_quit):
        self.on_toggle = on_toggle
        self.on_quit = on_quit
        self.status_item = None
        self.pystray_icon = None
        self._button_rect = None

    def get_target_position(self, window_width=360, window_height=270):
        """Calculates window position right next to the tray icon."""
        try:
            screen = webview.screens[0] if webview.screens else None
            sw = screen.width if screen else 1440
            sh = screen.height if screen else 900
        except Exception:
            sw, sh = 1440, 900

        if sys.platform == 'darwin':
            # On macOS: Tray is at top right.
            # If we have the exact NSStatusItem button frame, align right under it
            if self._button_rect:
                bx, bw = self._button_rect
                center_x = bx + bw / 2
                x = int(center_x - window_width / 2)
                # Clamp within screen bounds with 12px margin
                x = max(12, min(sw - window_width - 12, x))
            else:
                x = sw - window_width - 16
            y = 32 # Just below the 24-28px macOS menu bar
            return x, y
        elif sys.platform.startswith('win'):
            # On Windows: Tray is at bottom right.
            x = sw - window_width - 16
            y = sh - window_height - 60 # Above standard Windows taskbar
            return x, y
        else:
            # Linux / other: default to top right
            x = sw - window_width - 16
            y = 32
            return x, y

    def setup_tray(self):
        """Initializes system tray icon based on current OS."""
        if sys.platform == 'darwin':
            self._setup_mac_tray()
        else:
            self._setup_pystray()

    def _setup_mac_tray(self):
        try:
            from AppKit import (
                NSStatusBar,
                NSVariableStatusItemLength,
                NSImage,
                NSObject,
                NSMenu,
                NSMenuItem,
                NSEventMaskLeftMouseUp,
                NSEventMaskRightMouseUp,
                NSEventTypeRightMouseUp,
                NSApp
            )
            import objc

            class MacTrayHandler(NSObject):
                def initWithManager_(self, manager):
                    self = objc.super(MacTrayHandler, self).init()
                    if self:
                        self.manager = manager
                    return self

                @objc.IBAction
                def onClick_(self, sender):
                    event = NSApp.currentEvent()
                    if event and event.type() == NSEventTypeRightMouseUp:
                        # Show context menu on right click
                        if self.manager.status_item and self.manager.context_menu:
                            self.manager.status_item.popUpStatusItemMenu_(self.manager.context_menu)
                    else:
                        # Left click: update button coordinates and toggle window
                        self.manager._update_mac_button_rect()
                        if self.manager.on_toggle:
                            self.manager.on_toggle()

                @objc.IBAction
                def onMenuToggle_(self, sender):
                    self.manager._update_mac_button_rect()
                    if self.manager.on_toggle:
                        self.manager.on_toggle()

                @objc.IBAction
                def onMenuQuit_(self, sender):
                    if self.manager.on_quit:
                        self.manager.on_quit()

            self.handler = MacTrayHandler.alloc().initWithManager_(self)

            # Create status bar item
            self.status_item = NSStatusBar.systemStatusBar().statusItemWithLength_(NSVariableStatusItemLength)
            button = self.status_item.button()

            # Set icon (eye symbol with fallback to video symbol)
            img = NSImage.imageWithSystemSymbolName_accessibilityDescription_("eye.fill", "EyeDoc")
            if not img:
                img = NSImage.imageWithSystemSymbolName_accessibilityDescription_("video.fill", "EyeDoc")
            if img:
                img.setTemplate_(True)
                button.setImage_(img)
            else:
                button.setTitle_("👁 EyeDoc")

            # Setup click handler
            button.setTarget_(self.handler)
            button.setAction_('onClick:')
            button.sendActionOn_(NSEventMaskLeftMouseUp | NSEventMaskRightMouseUp)

            # Setup context menu for right-click
            menu = NSMenu.alloc().initWithTitle_("EyeDoc")
            item_toggle = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("Toggle Camera Window", "onMenuToggle:", "t")
            item_toggle.setTarget_(self.handler)
            menu.addItem_(item_toggle)

            menu.addItem_(NSMenuItem.separatorItem())

            item_quit = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_("Quit EyeDoc", "onMenuQuit:", "q")
            item_quit.setTarget_(self.handler)
            menu.addItem_(item_quit)

            self.context_menu = menu
            self._update_mac_button_rect()

        except Exception as e:
            print(f"[Tray] Error setting up macOS native tray: {e}")
            self._setup_pystray()

    def _update_mac_button_rect(self):
        try:
            if self.status_item:
                button = self.status_item.button()
                if button and button.window():
                    frame = button.window().frame()
                    self._button_rect = (frame.origin.x, frame.size.width)
        except Exception:
            pass

    def _setup_pystray(self):
        try:
            import pystray

            def on_pystray_toggle(icon, item):
                if self.on_toggle:
                    self.on_toggle()

            def on_pystray_quit(icon, item):
                icon.stop()
                if self.on_quit:
                    self.on_quit()

            menu = pystray.Menu(
                pystray.MenuItem("Toggle Camera Window", on_pystray_toggle, default=True),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("Quit EyeDoc", on_pystray_quit)
            )

            icon_image = create_default_tray_image()
            self.pystray_icon = pystray.Icon("eyedoc_tray", icon_image, "EyeDoc Camera", menu=menu)

            thread = threading.Thread(target=self.pystray_icon.run, daemon=True)
            thread.start()
        except Exception as e:
            print(f"[Tray] Error setting up pystray: {e}")
