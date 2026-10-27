# -*- mode: python ; coding: utf-8 -*-

a = Analysis(
    ['backend/app.py'],
    pathex=['backend'],          # so camera.py / tray.py / stream_server.py are found
    binaries=[],
    datas=[('frontend/dist', 'frontend/dist')],
    hiddenimports=[
        'camera',
        'stream_server',
        'tray',
        'cv2',
        'numpy',
        'bottle',
        'pystray',
        'PIL',
        'PIL.Image',
        'PIL.ImageDraw',
        'webview',
        'webview.platforms.cocoa',
    ],
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
    [],                         # onedir: binaries/datas go in COLLECT, not merged here
    exclude_binaries=True,      # required for onedir mode
    name='EyeDoc',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=True,        # Required on macOS for proper Finder/event handling
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
    name='EyeDoc',              # goes to dist/EyeDoc/
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
        'NSCameraUsageDescription': 'EyeDoc uses the camera to display your front camera feed in the menu bar.',
        'LSUIElement': True,
        'LSMultipleInstancesProhibited': True,
        'NSHighResolutionCapable': True,
        'NSRequiresAquaSystemAppearance': False,
    },
)

