# -*- mode: python ; coding: utf-8 -*-
import sys
from PyInstaller.utils.hooks import collect_all

is_win = sys.platform == 'win32'
is_mac = sys.platform == 'darwin'

datas_mp, binaries_mp, hiddenimports_mp = collect_all('mediapipe')

# Platform-specific hidden imports
if is_mac:
    platform_imports = [
        'webview.platforms.cocoa',
        'AppKit',
        'Quartz',
        'PyObjCTools',
        'PyObjCTools.AppHelper',
    ]
elif is_win:
    platform_imports = [
        'webview.platforms.edgechromium',
        'win32api',
        'win32con',
        'win32gui',
        'pystray._win32',
        'winotify',
        'winsound',
        'tkinter',
    ]
else:
    platform_imports = []

a = Analysis(
    ['backend/app.py'],
    pathex=['backend'],
    binaries=binaries_mp,
    datas=[
        ('frontend/dist', 'frontend/dist'),
        ('backend/models', 'backend/models'),
    ] + datas_mp,
    hiddenimports=[
        'camera',
        'stream_server',
        'blink_counter_server',
        'notifications',
        'minimal_view',
        'tray',
        'cv2',
        'numpy',
        'bottle',
        'cheroot',
        'cheroot.wsgi',
        'pystray',
        'PIL',
        'PIL.Image',
        'PIL.ImageDraw',
        'webview',
    ] + platform_imports + hiddenimports_mp,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='EyeDoc',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    # Windows requires .ico; macOS uses .icns or .png
    icon='./AppIcon.appiconset/appstore1024.ico' if is_win else './AppIcon.appiconset/appstore1024.png',
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='EyeDoc',
)

if is_mac:
    app = BUNDLE(
        coll,
        name='EyeDoc.app',
        icon='./AppIcon.appiconset/mac1024.png',
        bundle_identifier='com.eyedoc.desktop',
        info_plist={
            'CFBundleName': 'EyeDoc',
            'CFBundleDisplayName': 'EyeDoc',
            'CFBundleVersion': '1.0.1',
            'CFBundleShortVersionString': '1.0.1',
            'CFBundleIdentifier': 'com.eyedoc.desktop',
            'NSCameraUsageDescription': 'EyeDoc requires camera access for the live preview and blink counter.',
            'LSUIElement': True,
            'LSMultipleInstancesProhibited': True,
            'NSHighResolutionCapable': True,
            'NSRequiresAquaSystemAppearance': False,
        },
    )
