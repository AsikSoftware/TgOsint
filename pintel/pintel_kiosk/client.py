# -*- coding: utf-8 -*-
"""Сервер для киоска. Любая ошибка сети — ServerError с человеческим текстом;
оценки при обрыве связи копятся в очереди и досылаются."""
import json
import os
import threading
import time

import httpx

from . import __version__
from .config import app_dir, data_dir


class ServerError(RuntimeError):
    pass


class Client:
    """Связь с одним сервером на всю сеть.

    Ни адреса, ни токена на точке не настраивают: адрес и общий ключ привязки лежат в
    сборке, а свой токен киоск получает у сервера сам при первом выходе на связь и хранит
    рядом с остальными своими файлами. Раздача токенов по точкам осталась от версии, где
    каждый киоск заводили руками, — и ровно из-за неё ни одна точка не была подключена.
    """

    def __init__(self, cfg):
        self.base = (cfg.get("server") or "").rstrip("/")
        self.ключ = cfg.get("server_key") or ""
        self.точка = cfg.get("point") or ""
        self.enabled = bool(self.base)
        self.online = False
        self.last_error = ""
        self.qdir = os.path.join(data_dir(), "queue")
        self._замок = threading.Lock()
        self._токен_файл = os.path.join(data_dir(), "kiosk_token.json")
        self.token = self._прочитать_токен()

    # ---------- привязка к серверу ----------
    @staticmethod
    def машина() -> str:
        """Чем киоск узнаёт себя при следующем запуске. Имя машины стабильно и не требует
        файла: потеряется токен — сервер всё равно найдёт прежнюю строку, а не заведёт вторую."""
        import socket
        return (socket.gethostname() or "киоск")[:80]

    def _прочитать_токен(self) -> str:
        try:
            with open(self._токен_файл, encoding="utf-8") as f:
                return str(json.load(f).get("token") or "")
        except Exception:                                        # noqa: BLE001 — нет файла или он битый
            return ""

    def _сохранить_токен(self, token: str) -> None:
        os.makedirs(os.path.dirname(self._токен_файл), exist_ok=True)
        with open(self._токен_файл, "w", encoding="utf-8") as f:
            json.dump({"token": token, "машина": self.машина()}, f, ensure_ascii=False)

    def привязаться(self) -> str:
        """Получить у сервера свой токен. → токен. Ошибку отдаём словами, как и всё здесь."""
        with self._замок:
            try:
                with httpx.Client(base_url=self.base, timeout=20) as c:
                    r = c.post("/api/kiosk/register",
                               json={"key": self.ключ, "machine": self.машина(),
                                     "point": self.точка, "version": __version__})
            except httpx.HTTPError as e:
                self.online = False
                self.last_error = f"нет связи с сервером: {type(e).__name__}"
                raise ServerError(self.last_error)
            if r.status_code >= 400:
                try:
                    detail = r.json().get("detail")
                except Exception:                                # noqa: BLE001
                    detail = r.text[:200]
                self.last_error = f"киоск не привязался: {detail}"
                raise ServerError(self.last_error)
            токен = str((r.json() or {}).get("токен") or "")
            if not токен:
                raise ServerError("сервер не выдал токен киоска")
            self.token = токен
            try:
                self._сохранить_токен(токен)
            except OSError as e:
                self.last_error = f"токен не сохранился: {e}"    # работать можно, но до перезапуска
            return токен

    # ---------- низкий уровень ----------
    def _req(self, method, path, timeout=15, **kw):
        if not self.enabled:
            raise ServerError("адрес сервера пуст (kiosk.toml: server)")
        if not self.token:
            self.привязаться()
        try:
            with httpx.Client(base_url=self.base, timeout=timeout, headers={"X-Kiosk-Token": self.token}) as c:
                r = c.request(method, path, **kw)
            if r.status_code == 401 and path != "/api/kiosk/register":
                # токен протух или киоск завели заново — привязываемся и повторяем один раз
                self.привязаться()
                with httpx.Client(base_url=self.base, timeout=timeout,
                                  headers={"X-Kiosk-Token": self.token}) as c:
                    r = c.request(method, path, **kw)
        except httpx.HTTPError as e:
            self.online = False
            self.last_error = f"нет связи с сервером: {type(e).__name__}"
            raise ServerError(self.last_error)
        if r.status_code >= 400:
            try:
                detail = r.json().get("detail")
            except Exception:                                    # noqa: BLE001
                detail = r.text[:200]
            if r.status_code in (401, 403):
                self.online = False
            self.last_error = f"сервер ответил {r.status_code}: {detail}"
            raise ServerError(self.last_error)
        self.online = True
        self.last_error = ""
        return r.json()

    # ---------- API ----------
    def config(self):
        return self._req("GET", "/api/kiosk/config")


    def sickw(self, imei, services=None):
        """База IMEI — только через сервер: ключ живёт там, и там же общий кэш, поэтому один
        и тот же IMEI не оплачивается дважды. На точках ключу делать нечего.

        `services` — службы Sickw не по умолчанию: для запечатанного аппарата нужна другая
        (модель, объём, цвет и активация по IMEI с коробки), а не оператор и FMI."""
        тело = {"imei": imei}
        if services:
            тело["services"] = [int(s) for s in services]
        return self._req("POST", "/api/kiosk/sickw", json=тело, timeout=90)

    def local_number(self):
        """Номер талона, когда кассы нет: свой счётчик на каждый день."""
        path = os.path.join(data_dir(), "cache", "ticket_counter.json")
        day = time.strftime("%Y-%m-%d")
        try:
            c = json.load(open(path, encoding="utf-8"))
        except Exception:                                        # noqa: BLE001
            c = {}
        n = (c.get("n", 0) + 1) if c.get("day") == day else 1
        json.dump({"day": day, "n": n}, open(path, "w", encoding="utf-8"))
        return n

    def upload(self, payload):
        """→ ответ сервера или None, если оценка легла в очередь (нет связи).

        Сервера нет вовсе — в очередь не кладём: досылать некуда (flush_queue работает
        только при настроенном сервере), а те же слепок и отчёт уже лежат в папке out.
        Копия весит около мегабайта на оценку и росла бы вечно."""
        try:
            res = self._req("POST", "/api/kiosk/evaluations", json=payload, timeout=60)
        except ServerError:
            if self.enabled:
                path = os.path.join(self.qdir, f"{payload['client_id']}.json")
                json.dump(payload, open(path, "w", encoding="utf-8"), ensure_ascii=False)
            return None
        return res

    def update_evaluation(self, ev_id, report, snapshot_patch=None):
        return self._req("PATCH", f"/api/kiosk/evaluations/{ev_id}",
                         json={"report": report, "snapshot_patch": snapshot_patch}, timeout=60)

    # ---------- тест на телефоне клиента ----------
    def открыть_тест(self, токен, ev_id=None):
        """Завести сессию теста на сервере. → ссылка на страницу теста (на нашем домене).

        Нужна ровно для того, чтобы страница открывалась по HTTPS: по локальной сети Safari
        не пускает её к микрофону, а на домене пускает. Сервера нет — остаётся мини-сервер
        в самом киоске, шаг от этого не отменяется."""
        res = self._req("POST", "/api/kiosk/phone", json={"token": токен, "eval_id": ev_id}, timeout=15)
        return (res or {}).get("ссылка") or ""

    def результат_теста(self, токен):
        """→ результат теста или {}, пока телефон не ответил."""
        res = self._req("GET", f"/api/kiosk/phone/{токен}", timeout=15) or {}
        return res.get("результат") or {} if res.get("готов") else {}

    def intake(self, ev_id):
        """Состояние заявки: номер выдаёт сотрудник в кассе (после имени и телефона клиента); ссылка на отчёт для QR."""
        return self._req("GET", f"/api/kiosk/evaluations/{ev_id}/intake", timeout=15)

    def decision(self, ev_id, kind):
        return self._req("POST", f"/api/kiosk/evaluations/{ev_id}/decision", json={"decision": kind})

    def heartbeat(self, status):
        return self._req("POST", "/api/kiosk/heartbeat", json={"version": __version__, "status": status})

    def flush_queue(self, limit=20):
        """Дослать накопленное. → сколько ушло."""
        sent = 0
        for name in sorted(os.listdir(self.qdir))[:limit]:
            if not name.endswith(".json"):
                continue
            path = os.path.join(self.qdir, name)
            try:
                payload = json.load(open(path, encoding="utf-8"))
                self._req("POST", "/api/kiosk/evaluations", json=payload, timeout=60)
            except ServerError:
                break
            except Exception:                                    # noqa: BLE001 — битый файл
                os.rename(path, path + ".bad")
                continue
            os.remove(path)
            sent += 1
        return sent

    def queued(self):
        return len([n for n in os.listdir(self.qdir) if n.endswith(".json")])
