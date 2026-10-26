# -*- coding: utf-8 -*-
"""Запуск кассы одним файлом (pintel-server.exe): настройки из server.toml рядом,
база — SQLite-файл pintel.db рядом, меню по двойному щелчку.

Для нескольких точек правильнее VPS и docker compose (deploy/README.md),
но попробовать и работать на одной точке можно и так.
"""
import os
import socket
import sys
import threading
import time
import tomllib
import webbrowser

ENV_MAP = {
    "sickw_key": "PINTEL_SICKW_KEY", "sickw_services": "PINTEL_SICKW_SERVICES",
    "price_sheet_url": "PINTEL_PRICE_SHEET_URL", "gservice_json": "PINTEL_GSERVICE_JSON",
    "public_url": "PINTEL_PUBLIC_URL", "tz": "PINTEL_TZ", "currency": "PINTEL_CURRENCY",
    "secret_key": "PINTEL_SECRET_KEY", "database_url": "PINTEL_DATABASE_URL",
    "kiosk_return_seconds": "PINTEL_KIOSK_RETURN_SECONDS", "apple_history_seconds": "PINTEL_APPLE_HISTORY_SECONDS",
}


def app_dir():
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def lan_ip():
    """IP этого компьютера в локальной сети — чтобы QR с талона открывался с телефона."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:                                            # noqa: BLE001
        return "127.0.0.1"


def apply_config(path=None):
    """server.toml → переменные окружения (до импорта pintel_server.config)."""
    d = app_dir()
    p = path or os.path.join(d, "server.toml")
    cfg = {}
    if os.path.isfile(p):
        with open(p, "rb") as f:
            cfg = tomllib.load(f)
    port = int(cfg.get("port") or 8000)
    host = str(cfg.get("host") or "0.0.0.0")
    os.environ.setdefault("PINTEL_DATABASE_URL", "sqlite:///" + os.path.join(d, "pintel.db").replace("\\", "/"))
    gs = cfg.get("gservice_json") or "gservice.json"
    if not os.path.isabs(gs):
        gs = os.path.join(d, gs)
    cfg["gservice_json"] = gs
    for key, env in ENV_MAP.items():
        v = cfg.get(key)
        if v not in (None, ""):
            os.environ[env] = ",".join(str(x) for x in v) if isinstance(v, list) else str(v)
    if "PINTEL_PUBLIC_URL" not in os.environ:
        os.environ["PINTEL_PUBLIC_URL"] = f"http://{lan_ip()}:{port}"
    if "PINTEL_SECRET_KEY" not in os.environ:
        os.environ["PINTEL_SECRET_KEY"] = "local-" + socket.gethostname()
    return {"host": host, "port": port, "path": p, "db": os.environ["PINTEL_DATABASE_URL"]}


def say(*a):
    print(*a, flush=True)


def run_server(host, port, open_browser=True):
    import uvicorn
    from .main import app
    url = f"http://127.0.0.1:{port}"
    if open_browser:
        threading.Timer(1.5, lambda: webbrowser.open(url)).start()
    say(f"Касса: {url}  (с других компьютеров сети: {os.environ.get('PINTEL_PUBLIC_URL')})")
    say("Окно не закрывайте — это и есть сервер. Ctrl+C — остановить.\n")
    uvicorn.run(app, host=host, port=port, log_level="warning", proxy_headers=True)


def has_admin():
    from sqlalchemy import select
    from .db import SessionLocal, init_db
    from .models import ROLE_ADMIN, User
    init_db()
    db = SessionLocal()
    try:
        return db.scalar(select(User).where(User.role == ROLE_ADMIN)) is not None
    finally:
        db.close()


def interactive(rc):
    from . import cli
    from .config import settings
    menu = f"""
  ┌──────────────────────────────────────────────────────┐
  │  PINTEL SERVER — касса сотрудника                     │
  ├──────────────────────────────────────────────────────┤
  │  1  Запустить кассу (откроется в браузере)            │
  │  2  Создать администратора                            │
  │  3  Создать киоск и выдать токен                      │
  │  4  Обновить прайс из Google Таблицы                  │
  │  5  Проверить настройки (ключи, база, адрес)          │
  │  0  Выход                                             │
  └──────────────────────────────────────────────────────┘
  база: {rc['db']}
  настройки: {rc['path']}{'' if os.path.isfile(rc['path']) else ' (нет — используются значения по умолчанию)'}"""
    if not has_admin():
        say("\nАдминистратора ещё нет — создайте его (пункт 2), иначе войти в кассу не получится.")
    while True:
        say(menu)
        try:
            choice = input("  Выбор: ").strip()
        except EOFError:
            return 0
        try:
            if choice == "1":
                if not has_admin():
                    say("  сначала создайте администратора (пункт 2)")
                    continue
                run_server(rc["host"], rc["port"])
            elif choice == "2":
                login = input("  логин (например admin): ").strip() or "admin"
                name = input("  имя (как показывать в кассе): ").strip() or "Администратор"
                cli.main(["create-admin", "--login", login, "--name", name])
            elif choice == "3":
                name = input("  имя киоска (например Алматы-1): ").strip() or "Киоск-1"
                point = input("  точка (Enter — без точки): ").strip()
                cli.main(["create-kiosk", "--name", name] + (["--point", point] if point else []))
            elif choice == "4":
                cli.main(["fetch-price"])
            elif choice == "5":
                say(f"  адрес кассы: {settings.public_url}")
                say(f"  ключ Sickw: {'задан' if settings.sickw_key else 'нет (server.toml → sickw_key)'}")
                say(f"  gservice.json: {'найден' if os.path.isfile(settings.gservice_json) else 'не найден: ' + settings.gservice_json}")
                say(f"  прайс: {settings.price_sheet_url[:60]}…")
                say(f"  часовой пояс: {settings.tz}, валюта: {settings.currency}")
            elif choice in ("0", "q", ""):
                return 0
            else:
                say("  нет такого пункта")
        except KeyboardInterrupt:
            say("\n  остановлено")
        except Exception as e:                                   # noqa: BLE001
            say(f"\n  ОШИБКА: {type(e).__name__}: {e}")
            try:
                with open(os.path.join(app_dir(), "server_errors.log"), "a", encoding="utf-8") as f:
                    import traceback
                    f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {traceback.format_exc()}\n")
            except Exception:                                    # noqa: BLE001
                pass


def main(argv=None):
    if os.name == "nt":
        os.system("chcp 65001 >nul")
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:                                        # noqa: BLE001
            pass
    rc = apply_config()
    argv = sys.argv[1:] if argv is None else argv
    if not argv:
        code = interactive(rc)
        if os.name == "nt":
            try:
                input("\nEnter — закрыть окно")
            except EOFError:
                pass
        return code
    if argv[0] == "run":
        run_server(rc["host"], rc["port"], open_browser="--no-browser" not in argv)
        return 0
    from . import cli
    return cli.main(argv)


if __name__ == "__main__":
    sys.exit(main())
