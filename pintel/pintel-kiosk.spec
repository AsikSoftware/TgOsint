# -*- mode: python ; coding: utf-8 -*-
# Сборка киоска: python -m PyInstaller --clean --noconfirm pintel-kiosk.spec
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

hidden = ['pymobiledevice3.remote.userspace_tunnel', 'pymobiledevice3.remote.core_device.device_info', 'pmd_pytcp', 'pmd_pytcp.stack', 'pmd_pytcp.socket', 'pmd_pytcp.lib.interface_layer', 'pmd_pytcp.lib.io_backend', 
          'pymobiledevice3.services.diagnostics', 'pymobiledevice3.services.syslog', 'pymobiledevice3.services.afc',
          'pymobiledevice3.services.mobile_config', 'google.auth.transport.requests', 'requests', 'rsa',
          'pintel_core.external.gsheet',
          'pymobiledevice3.usbmux', 'pymobiledevice3.lockdown', 'httpx', 'qrcode', 'pintel_kiosk.app']
datas = collect_data_files('pymobiledevice3') + [
    ('pintel_core/analysis/models.json', 'pintel_core/analysis'),
    ('pintel_kiosk/assets', 'pintel_kiosk/assets'),
]
excludes = ['tkinter', 'matplotlib', 'av', 'jedi', 'IPython', 'parso', 'numpy', 'PIL', 'pillow', 'pandas', 'scipy',
            'qh3', 'aiohttp', 'fastapi', 'uvicorn', 'starlette', 'sqlalchemy', 'alembic', 'pintel_server',
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

a = Analysis(['kiosk_main.py'], pathex=['.'], binaries=[], datas=datas, hiddenimports=hidden, hookspath=[],
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
