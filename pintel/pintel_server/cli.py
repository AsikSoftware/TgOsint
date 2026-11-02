# -*- coding: utf-8 -*-
"""Команды администратора:
  python -m pintel_server.cli init-db
  python -m pintel_server.cli create-admin --login admin --name "Руслан" [--password …]
  python -m pintel_server.cli create-kiosk --name "Алматы-1" [--point "Алматы-1"]
  python -m pintel_server.cli fetch-price
  python -m pintel_server.cli run [--port 8000]
"""
import argparse
import getpass
import sys

from sqlalchemy import select

from .auth import hash_password, new_kiosk_token
from .db import SessionLocal, init_db
from .models import ROLE_ADMIN, Kiosk, Point, User
from .services import price as price_service


def main(argv=None):
    ap = argparse.ArgumentParser(prog="pintel-server")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init-db")
    s = sub.add_parser("create-admin"); s.add_argument("--login", required=True); s.add_argument("--name", required=True); s.add_argument("--password")
    s = sub.add_parser("create-kiosk"); s.add_argument("--name", required=True); s.add_argument("--point")
    sub.add_parser("fetch-price")
    s_prune = sub.add_parser("prune")        # убрать сырые слепки у старых оценок
    s_prune.add_argument("--days", type=int, default=None)
    sub.add_parser("sync-shops")             # завести точки по магазинам Оценки (те же id)
    sub.add_parser("points")                 # показать точки и их токены
    s = sub.add_parser("run"); s.add_argument("--host", default="0.0.0.0"); s.add_argument("--port", type=int, default=8000)
    a = ap.parse_args(argv)

    if a.cmd == "init-db":
        init_db(); print("таблицы созданы"); return 0
    if a.cmd == "run":
        import uvicorn
        uvicorn.run("pintel_server.main:app", host=a.host, port=a.port, proxy_headers=True)
        return 0
    db = SessionLocal()
    try:
        if a.cmd == "create-admin":
            init_db()
            pw = a.password or getpass.getpass("пароль администратора: ")
            if len(pw) < 6:
                print("пароль не короче 6 знаков"); return 2
            if db.scalar(select(User).where(User.login == a.login.lower())):
                print("такой логин уже есть"); return 2
            db.add(User(login=a.login.lower(), name=a.name, role=ROLE_ADMIN, password_hash=hash_password(pw)))
            db.commit(); print(f"администратор {a.login} создан"); return 0
        if a.cmd == "create-kiosk":
            point = None
            if a.point:
                point = db.scalar(select(Point).where(Point.name == a.point)) or Point(name=a.point)
                db.add(point); db.flush()
            token, h = new_kiosk_token()
            db.add(Kiosk(name=a.name, token_hash=h, point_id=point.id if point else None))
            db.commit()
            print(f"киоск «{a.name}» создан\nтокен (показывается один раз): {token}"); return 0
        if a.cmd == "fetch-price":
            row = price_service.refresh(db)
            print(f"прайс: {row.models_count} моделей, {row.positions_count} позиций"); return 0
        if a.cmd == "sync-shops":
            from .services import points as points_service
            итог = points_service.синхронизировать(db)
            for ключ, подпись in (("создано", "новые точки"), ("переименовано", "переименованы"),
                                  ("пропали", "ПРОПАЛИ В ОЦЕНКЕ (работают, но проверьте)")):
                if итог[ключ]:
                    print(f"{подпись}: " + "; ".join(итог[ключ]))
            print(f"токенов выдано: {итог['токенов_выдано']}")
            a.cmd = "points"                 # сразу показываем, что получилось
        if a.cmd == "points":
            from .services import points as points_service
            for p in points_service.список(db):
                состояние = "" if p.is_active else "  (отключена)"
                состояние += "  (в Оценке такого магазина нет)" if points_service.пропала(p) else ""
                print(f"{p.id:>3}  {p.litera or '--':<3}  {p.name:<24}  {p.token or 'токена нет'}{состояние}")
            return 0
        if a.cmd == "prune":
            from .services import evaluations as ev_service
            n = ev_service.prune_snapshots(db, a.days)
            e = ev_service.prune_references(db, a.days)
            print(f"убрано: слепков у {n} оценок, эталонов {e} (сами оценки остались)"); return 0
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
