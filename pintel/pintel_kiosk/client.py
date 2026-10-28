# -*- coding: utf-8 -*-
"""Сервер для киоска. Любая ошибка сети — ServerError с человеческим текстом;
оценки при обрыве связи копятся в очереди и досылаются."""
import json
import os
import time

import httpx

from . import __version__
from .config import app_dir, data_dir


class ServerError(RuntimeError):
    pass


class Client:
    def __init__(self, cfg):
        self.base = cfg.get("server") or ""
        self.token = cfg.get("token") or ""
        self.enabled = bool(self.base and self.token)
        self.online = False
        self.last_error = ""
        self.qdir = os.path.join(data_dir(), "queue")
        # автономный режим: ключи на самом киоске. Прайса здесь нет — цену считает бот
        # Оценки по своему прайсу, и наша цифра всё равно была бы другой.
        self.sickw_key = str(cfg.get("sickw_key") or "")
        self.sickw_services = cfg.get("sickw_services") or [61]

    @property
    def local_sickw(self):
        return bool(self.sickw_key)

    @property
    def standalone_ready(self):
        """Без сервера киоск полноценен, если может проверить телефон по базе IMEI."""
        return self.local_sickw

    # ---------- низкий уровень ----------
    def _req(self, method, path, timeout=15, **kw):
        if not self.enabled:
            raise ServerError("сервер не настроен (kiosk.toml: server, token)")
        try:
            with httpx.Client(base_url=self.base, timeout=timeout, headers={"X-Kiosk-Token": self.token}) as c:
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


    def sickw(self, imei):
        """Через сервер (ключ там); без сервера или при его недоступности — ключом из kiosk.toml."""
        if self.enabled:
            try:
                return self._req("POST", "/api/kiosk/sickw", json={"imei": imei}, timeout=90)
            except ServerError:
                if not self.local_sickw:
                    raise
        if self.local_sickw:
            from pintel_core.external import sickw as sk
            try:
                return sk.lookup_many(imei, self.sickw_key, self.sickw_services,
                                      cache_dir=os.path.join(data_dir(), "cache", "sickw"))
            except Exception as e:                               # noqa: BLE001
                raise ServerError(f"Sickw: {e}")
        raise ServerError("Sickw: нет ни сервера, ни ключа sickw_key в kiosk.toml")

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
