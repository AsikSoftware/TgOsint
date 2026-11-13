# -*- coding: utf-8 -*-
"""Точка входа для PyInstaller (без относительных импортов)."""
import sys

if "--selftest" in sys.argv:
    # Самопроверка собранного exe — до окна и до Qt: всё ли, чем читается телефон, загружается.
    # Её запускает сборка перед релизом (см. pintel_core/selfcheck.py).
    from pintel_core import selfcheck
    i = sys.argv.index("--selftest")
    sys.exit(selfcheck.main(sys.argv[i + 1] if len(sys.argv) > i + 1 else None))

from pintel_kiosk.app import main
sys.exit(main())
