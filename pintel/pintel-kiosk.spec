# -*- mode: python ; coding: utf-8 -*-
# Сборка киоска: python -m PyInstaller --clean --noconfirm pintel-kiosk.spec
import glob
import os

from PyInstaller.utils.hooks import collect_data_files, collect_submodules, collect_all

hidden = ['pymobiledevice3.remote.userspace_tunnel', 'pymobiledevice3.remote.core_device.device_info', 'pmd_pytcp', 'pytun_pmd3', 'pmd_pytcp.stack', 'pmd_pytcp.socket', 'pmd_pytcp.lib.interface_layer', 'pmd_pytcp.lib.io_backend', 
          'pymobiledevice3.services.diagnostics', 'pymobiledevice3.services.syslog', 'pymobiledevice3.services.afc',
          'pymobiledevice3.services.mobile_config', 'google.auth.transport.requests', 'requests', 'rsa',
          'pintel_core.external.gsheet', 'pintel_core.external.ocenka', 'pintel_core.receipt',
          'pintel_core.external.ocenka_tg', 'pintel_core.external.ocenka_media', 'pintel_kiosk.ui_deal',
          'pymobiledevice3.usbmux', 'pymobiledevice3.lockdown', 'httpx', 'qrcode', 'pintel_kiosk.app']
_pmd_datas, _pmd_bins, _pmd_hidden = collect_all('pmd_pytcp')
_cd_datas, _cd_bins, _cd_hidden = collect_all('pymobiledevice3.remote')
# wintun.dll из pytun_pmd3: без него userspace-туннель CoreDevice не поднимается, а значит
# на iOS 17.4+ не читается MobileGestalt (цвет корпуса, серийники панели и ИК-камеры Face ID).
# Собранный exe искал его по пути _internal/pytun_pmd3/wintun/bin/amd64/wintun.dll и не находил:
# спеки собирали pmd_pytcp, но не сам pytun_pmd3. Найдено на эталоне iPhone 14 Pro (iOS 26.5).
import importlib.util as _ilu
_tun_datas, _tun_bins, _tun_hidden = collect_all('pytun_pmd3')
_tun_spec = _ilu.find_spec('pytun_pmd3')
_tun_dir = os.path.dirname(_tun_spec.origin) if _tun_spec and _tun_spec.origin else None
_wintun = [p for p in glob.glob(os.path.join(_tun_dir or '.', '**', 'wintun.dll'), recursive=True)
           if 'amd64' in p] or glob.glob(os.path.join(_tun_dir or '.', '**', 'wintun.dll'), recursive=True)
if not _wintun:
    raise SystemExit('нет wintun.dll в pytun_pmd3: туннель CoreDevice не заработает, '
                     'а на iOS 17.4+ пропадёт часть данных по кабелю. Переустановите pymobiledevice3.')
_tun_datas += [(_wintun[0], os.path.relpath(os.path.dirname(_wintun[0]), os.path.dirname(_tun_dir)))]

datas = collect_data_files('pymobiledevice3') + _pmd_datas + _cd_datas + _tun_datas + [
    ('pintel_core/analysis/models.json', 'pintel_core/analysis'),
    ('pintel_kiosk/assets', 'pintel_kiosk/assets'),
]
excludes = ['tkinter', 'matplotlib', 'av', 'jedi', 'IPython', 'parso', 'numpy', 'PIL', 'pillow', 'pandas', 'scipy',
            # сделку создаёт бот Оценки, в её базу с точки хода нет — драйвер базы не нужен
            'sqlalchemy', 'psycopg', 'psycopg2',
            'aiohttp', 'fastapi', 'uvicorn', 'starlette', 'alembic', 'pintel_server',
            'PySide6.QtWebEngineCore', 'PySide6.QtWebEngineWidgets', 'PySide6.QtWebEngineQuick', 'PySide6.QtQml',
            'PySide6.QtQuick', 'PySide6.QtQuickWidgets', 'PySide6.QtQuickControls2', 'PySide6.Qt3DCore',
            'PySide6.Qt3DRender', 'PySide6.QtMultimedia', 'PySide6.QtMultimediaWidgets', 'PySide6.QtPdf',
            'PySide6.QtPdfWidgets', 'PySide6.QtCharts', 'PySide6.QtDataVisualization', 'PySide6.QtSql',
            'PySide6.QtTest', 'PySide6.QtBluetooth', 'PySide6.QtNfc', 'PySide6.QtPositioning', 'PySide6.QtLocation',
            'PySide6.QtRemoteObjects', 'PySide6.QtScxml', 'PySide6.QtSensors', 'PySide6.QtSerialPort',
            'PySide6.QtWebSockets', 'PySide6.QtWebChannel', 'PySide6.QtDesigner', 'PySide6.QtHelp', 'PySide6.QtOpenGL',
            'PySide6.QtOpenGLWidgets', 'PySide6.QtPrintSupport', 'PySide6.QtSvgWidgets', 'PySide6.QtTextToSpeech',
            'PySide6.QtUiTools', 'PySide6.QtXml', 'PySide6.QtNetworkAuth', 'PySide6.QtHttpServer', 'PySide6.QtSpatialAudio',
            'PySide6.QtStateMachine', 'PySide6.QtGraphs', 'PySide6.QtAsyncio', 'PySide6.QtConcurrent']

a = Analysis(['kiosk_main.py'], pathex=['.'], binaries=_pmd_bins + _cd_bins + _tun_bins, datas=datas, hiddenimports=hidden + _pmd_hidden + _cd_hidden + _tun_hidden, hookspath=[],
             runtime_hooks=[], excludes=excludes, noarchive=False)
# хук PySide6 тащит весь Qt — выкидываем тяжёлые модули по имени файла
heavy = ('WebEngine', 'Qml', 'Quick', 'Multimedia', 'Pdf', 'Charts', 'DataVisualization', '3D', 'Designer', 'Help',
         'Location', 'Positioning', 'Sensors', 'SerialPort', 'Bluetooth', 'Nfc', 'RemoteObjects', 'Scxml', 'Sql',
         'Test', 'WebSockets', 'WebChannel', 'VirtualKeyboard', 'TextToSpeech', 'Graphs', 'HttpServer', 'opengl32sw',
         'd3dcompiler', 'ffmpeg', 'avcodec', 'avformat', 'avutil', 'swresample', 'swscale', 'translations')
a.binaries = [b for b in a.binaries if not any(h.lower() in b[0].lower() for h in heavy)]
a.datas = [d for d in a.datas if not any(h.lower() in d[0].lower() for h in heavy)]
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='pintel-kiosk', debug=False, bootloader_ignore_signals=False,
          strip=False, upx=False, console=False, icon='pintel_kiosk/assets/icon.ico')
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='pintel-kiosk')
