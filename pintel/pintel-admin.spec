# -*- mode: python ; coding: utf-8 -*-
# Административная программа: python -m PyInstaller --clean --noconfirm pintel-admin.spec
#
# Она намного легче кассы: телефоны не читает, в сеть ходит только к нашему серверу. Поэтому
# ни pymobiledevice3, ни туннелей, ни драйверов здесь нет — только окно, шрифты и httpx.
import os
import sys

hidden = ['pintel_admin.app', 'pintel_admin.ui', 'pintel_admin.client', 'pintel_admin.config',
          'pintel_kiosk.ui', 'httpx']

datas = [
    ('pintel_kiosk/assets/fonts', 'pintel_kiosk/assets/fonts'),   # облик общий с кассой
    ('pintel_kiosk/assets/logo.png', 'pintel_kiosk/assets'),
]

excludes = [
    'tkinter', 'matplotlib', 'numpy', 'PIL', 'pandas', 'scipy', 'IPython', 'jedi', 'parso',
    'pymobiledevice3', 'pmd_pytcp', 'pytun_pmd3', 'pyimg4', 'construct', 'qh3',
    'sqlalchemy', 'psycopg', 'psycopg2', 'alembic', 'fastapi', 'uvicorn', 'starlette',
    'pintel_server', 'pintel_core.devicelink', 'qrcode',
    'PySide6.QtWebEngineCore', 'PySide6.QtWebEngineWidgets', 'PySide6.QtQml', 'PySide6.QtQuick',
    'PySide6.QtMultimedia', 'PySide6.QtPdf', 'PySide6.QtCharts', 'PySide6.Qt3DCore',
    'PySide6.QtSql', 'PySide6.QtTest', 'PySide6.QtBluetooth', 'PySide6.QtNfc',
    'PySide6.QtPositioning', 'PySide6.QtSerialPort', 'PySide6.QtWebSockets', 'PySide6.QtDesigner',
]

a = Analysis(['admin_main.py'], pathex=['.'], binaries=[], datas=datas, hiddenimports=hidden,
             hookspath=[], runtime_hooks=[], excludes=excludes, noarchive=False)
heavy = ('WebEngine', 'Qml', 'Quick', 'Multimedia', 'Pdf', 'Charts', 'DataVisualization', '3D',
         'Designer', 'Help', 'Location', 'Positioning', 'Sensors', 'SerialPort', 'Bluetooth',
         'Nfc', 'RemoteObjects', 'Scxml', 'Sql', 'Test', 'WebSockets', 'WebChannel',
         'VirtualKeyboard', 'TextToSpeech', 'Graphs', 'HttpServer', 'opengl32sw', 'd3dcompiler',
         'ffmpeg', 'avcodec', 'avformat', 'avutil', 'swresample', 'swscale', 'translations')
a.binaries = [b for b in a.binaries if not any(h.lower() in b[0].lower() for h in heavy)]
a.datas = [d for d in a.datas if not any(h.lower() in d[0].lower() for h in heavy)]

if sys.platform == 'darwin':
    _значок = os.path.abspath('pintel_kiosk/assets/icon.icns')
    if not os.path.exists(_значок):
        import subprocess as _sp
        _sp.check_call([sys.executable, 'tools/mac_icon.py', 'pintel_kiosk/assets/icon.ico', _значок])
else:
    _значок = 'pintel_kiosk/assets/icon.ico'

pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='pintel-admin', debug=False,
          bootloader_ignore_signals=False, strip=False, upx=False, console=False, icon=_значок)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='pintel-admin')
if sys.platform == 'darwin':
    app = BUNDLE(coll, name='pintel-admin.app', icon=_значок, bundle_identifier='kz.pintel.admin',
                 info_plist={
                     'CFBundleName': 'Pintel Управление',
                     'CFBundleDisplayName': 'Pintel Управление',
                     'CFBundleShortVersionString': '0.1.0',
                     'NSHighResolutionCapable': True,
                     'LSApplicationCategoryType': 'public.app-category.business',
                 })
