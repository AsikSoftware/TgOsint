# -*- coding: utf-8 -*-
"""Сервер для киоска. Любая ошибка сети — ServerError с человеческим текстом;
оценки при обрыве связи копятся в очереди и досылаются."""
import json
import os
import time

import httpx

from . import __version__
from .config import data_dir


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
        self.cache = os.path.join(data_dir(), "cache", "price_grid.json")

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

    def price(self, force=False):
        """Сетка прайса с сервера; при обрыве — последняя сохранённая."""
        if self.enabled:
            try:
                p = self._req("GET", "/api/kiosk/price", timeout=30)
                grid = p["сетка"]
                grid["_версия"], grid["_обновлён"] = p.get("версия"), p.get("обновлён")
                json.dump(grid, open(self.cache, "w", encoding="utf-8"), ensure_ascii=False)
                return grid
            except ServerError:
                if force:
                    raise
        if os.path.isfile(self.cache):
            return json.load(open(self.cache, encoding="utf-8"))
        return None

    def sickw(self, imei):
        return self._req("POST", "/api/kiosk/sickw", json={"imei": imei}, timeout=90)

    def upload(self, payload):
        """→ ответ сервера или None, если оценка легла в очередь (нет связи)."""
        try:
            res = self._req("POST", "/api/kiosk/evaluations", json=payload, timeout=60)
        except ServerError:
            path = os.path.join(self.qdir, f"{payload['client_id']}.json")
            json.dump(payload, open(path, "w", encoding="utf-8"), ensure_ascii=False)
            return None
        return res

    def update_evaluation(self, ev_id, report, snapshot_patch=None):
        return self._req("PATCH", f"/api/kiosk/evaluations/{ev_id}",
                         json={"report": report, "snapshot_patch": snapshot_patch}, timeout=60)

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
