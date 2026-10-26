# -*- mode: python ; coding: utf-8 -*-
# Сборка кассы одним файлом: python -m PyInstaller --clean --noconfirm pintel-server.spec
hidden = ['uvicorn.logging', 'uvicorn.loops', 'uvicorn.loops.auto', 'uvicorn.loops.asyncio',
          'uvicorn.protocols', 'uvicorn.protocols.http', 'uvicorn.protocols.http.auto', 'uvicorn.protocols.http.h11_impl',
          'uvicorn.protocols.websockets', 'uvicorn.protocols.websockets.auto', 'uvicorn.lifespan', 'uvicorn.lifespan.on',
          'uvicorn.lifespan.off', 'sqlalchemy.dialects.sqlite', 'anyio._backends._asyncio', 'multipart', 'python_multipart',
          'jinja2', 'google.auth.transport.requests', 'requests', 'rsa', 'h11', 'pintel_server.cli', 'pintel_server.launcher']
datas = [('pintel_server/templates', 'pintel_server/templates'), ('pintel_server/static', 'pintel_server/static'),
         ('pintel_core/analysis/models.json', 'pintel_core/analysis')]
excludes = ['tkinter', 'PySide6', 'PyQt5', 'matplotlib', 'av', 'jedi', 'IPython', 'parso', 'numpy', 'PIL', 'pillow',
            'pandas', 'scipy', 'qh3', 'aiohttp', 'pymobiledevice3', 'pintel_kiosk', 'psycopg', 'alembic']

a = Analysis(['server_main.py'], pathex=['.'], binaries=[], datas=datas, hiddenimports=hidden, hookspath=[],
             runtime_hooks=[], excludes=excludes, noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='pintel-server', debug=False, bootloader_ignore_signals=False,
          strip=False, upx=False, console=True, icon='pintel_kiosk/assets/icon.ico')
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='pintel-server')
