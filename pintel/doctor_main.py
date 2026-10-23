"""Точка входа для PyInstaller: пакет импортируется абсолютно."""
import sys
from pintel_core.doctor import main
sys.exit(main())
