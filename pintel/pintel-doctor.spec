# -*- mode: python ; coding: utf-8 -*-
# Консольная сборка «врача». pymobiledevice3 подгружает модули динамически —
# собираем всё его дерево целиком.
import glob
import os

from PyInstaller.utils.hooks import collect_all, collect_submodules, collect_data_files

# Только то, что реально импортируем: lockdown, usbmux, diagnostics, syslog.
hidden = ['pymobiledevice3.remote.userspace_tunnel', 'pymobiledevice3.remote.core_device.device_info', 'pmd_pytcp', 'pytun_pmd3', 'pmd_pytcp.stack', 'pmd_pytcp.socket', 'pmd_pytcp.lib.interface_layer', 'pmd_pytcp.lib.io_backend', 'pymobiledevice3.services.mobile_config', 'google.auth.transport.requests', 'requests', 'rsa', 'pymobiledevice3.services.diagnostics',
          'pymobiledevice3.services.syslog', 'pymobiledevice3.usbmux', 'pymobiledevice3.lockdown']
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

datas = collect_data_files('pymobiledevice3') + _pmd_datas + _cd_datas + _tun_datas + [('pintel_core/analysis/models.json', 'pintel_core/analysis')]

a = Analysis(['doctor_main.py'], pathex=['.'], binaries=_pmd_bins + _cd_bins + _tun_bins, datas=datas,
             hiddenimports=hidden + _pmd_hidden + _cd_hidden + _tun_hidden, hookspath=[], runtime_hooks=[],
             # Тяжёлые опциональные части pymobiledevice3 (видео, IPython, numpy) нам не нужны
             excludes=['tkinter', 'PySide6', 'PyQt5', 'matplotlib', 'av', 'jedi', 'IPython', 'parso',
                       'numpy', 'PIL', 'pillow', 'pandas', 'scipy',
                       'aiohttp', 'fastapi', 'uvicorn', 'starlette'], noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='pintel-doctor',
          debug=False, strip=False, upx=False, console=True)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='pintel-doctor')
