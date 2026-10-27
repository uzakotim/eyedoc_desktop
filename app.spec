# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all

datas_mp, binaries_mp, hiddenimports_mp = collect_all('mediapipe')

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
        'webview.platforms.cocoa',
    ] + hiddenimports_mp,
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
    icon='./AppIcon.appiconset/appstore1024.png'
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

app = BUNDLE(
    coll,
    name='EyeDoc.app',
    icon='./AppIcon.appiconset/mac1024.png',
    bundle_identifier='com.eyedoc.desktop',
    info_plist={
        'CFBundleName': 'EyeDoc',
        'CFBundleDisplayName': 'EyeDoc',
        'CFBundleVersion': '1.0.0',
        'CFBundleShortVersionString': '1.0.0',
        'CFBundleIdentifier': 'com.eyedoc.desktop',
        'NSCameraUsageDescription': 'EyeDoc requires camera access for the live preview and blink counter.',
        'LSUIElement': True,
        'LSMultipleInstancesProhibited': True,
        'NSHighResolutionCapable': True,
        'NSRequiresAquaSystemAppearance': False,
    },
)
