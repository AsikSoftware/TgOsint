# -*- mode: python ; coding: utf-8 -*-
# Консольная сборка «врача». pymobiledevice3 подгружает модули динамически —
# собираем всё его дерево целиком.
from PyInstaller.utils.hooks import collect_submodules, collect_data_files

# Только то, что реально импортируем: lockdown, usbmux, diagnostics, syslog.
hidden = ['pymobiledevice3.remote.userspace_tunnel', 'pymobiledevice3.remote.core_device.device_info', 'pmd_pytcp', 'pmd_pytcp.stack', 'pmd_pytcp.socket', 'pmd_pytcp.lib.interface_layer', 'pmd_pytcp.lib.io_backend', 'pymobiledevice3.services.mobile_config', 'google.auth.transport.requests', 'requests', 'rsa', 'pymobiledevice3.services.diagnostics',
          'pymobiledevice3.services.syslog', 'pymobiledevice3.usbmux', 'pymobiledevice3.lockdown']
datas = collect_data_files('pymobiledevice3') + [('pintel_core/analysis/models.json', 'pintel_core/analysis')]

a = Analysis(['doctor_main.py'], pathex=['.'], binaries=[], datas=datas,
             hiddenimports=hidden, hookspath=[], runtime_hooks=[],
             # Тяжёлые опциональные части pymobiledevice3 (видео, IPython, numpy) нам не нужны
             excludes=['tkinter', 'PySide6', 'PyQt5', 'matplotlib', 'av', 'jedi', 'IPython', 'parso',
                       'numpy', 'PIL', 'pillow', 'pandas', 'scipy',
                       'qh3', 'aiohttp', 'fastapi', 'uvicorn', 'starlette'], noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='pintel-doctor',
          debug=False, strip=False, upx=False, console=True)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='pintel-doctor')
