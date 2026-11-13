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

    Адрес зашит в сборку, токен — у ТОЧКИ: его вводят в самой программе один раз и меняют
    через меню администратора. В файле настроек на точке нет ни того, ни другого — настройки
    тоже приходят отсюда. Имя машины идёт отдельным заголовком: так на сервере видно, сколько
    компьютеров на точке и когда каждый был на связи, а второй киоск не требует второго
    токена.
    """

    def __init__(self, cfg):
        self.base = (cfg.get("server") or "").rstrip("/")
        self.token = str(cfg.get("token") or "")
        self.enabled = bool(self.base and self.token)
        self.online = False
        self.last_error = ""
        self.qdir = os.path.join(data_dir(), "queue")
        self._замок = threading.Lock()

    def сменить_токен(self, токен: str) -> None:
        self.token = str(токен or "").strip()
        self.enabled = bool(self.base and self.token)

    def точки(self) -> list:
        """Список точек для первой настройки: без токена, его ещё не ввели.

        Точка у нас — это магазин Оценки с тем же id, поэтому сотрудник выбирает её из
        знакомого списка, а не придумывает имя."""
        import httpx as _httpx
        try:
            with _httpx.Client(base_url=self.base, timeout=15) as c:
                r = c.get("/api/kiosk/points")
        except _httpx.HTTPError as e:
            raise ServerError(f"нет связи с сервером: {type(e).__name__}")
        if r.status_code >= 400:
            raise ServerError(f"сервер ответил {r.status_code}")
        return (r.json() or {}).get("точки") or []

    @staticmethod
    def машина() -> str:
        """Чем компьютер назовётся серверу. Имя машины стабильно и не требует файла.

        В заголовок оно едет закодированным: на точке компьютер вполне может называться
        «Касса-1», а заголовки HTTP — это ascii, и httpx на таком имени просто падает."""
        import socket
        from urllib.parse import quote
        return quote((socket.gethostname() or "киоск")[:80], safe="")

    # ---------- низкий уровень ----------
    def _req(self, method, path, timeout=15, **kw):
        if not self.enabled:
            raise ServerError("нет токена точки — введите его в программе")
        try:
            with httpx.Client(base_url=self.base, timeout=timeout,
                              headers={"X-Kiosk-Token": self.token,
                                       "X-Kiosk-Machine": self.машина()}) as c:
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

    def история(self, имеи, кроме=None):
        """Что с этим аппаратом у нас уже было — по IMEI.

        Это подсказка сотруднику, а не часть проверки: ждать её дольше, чем он читает экран,
        незачем, и её неудача ничего не ломает — вызывающий покажет причину в углу."""
        параметры = {}
        for имя, значение in zip(("imei", "imei2"), [x for x in (имеи or ()) if str(x or "").strip()]):
            параметры[имя] = str(значение).strip()
        if кроме:
            параметры["ev_id"] = int(кроме)
        return self._req("GET", "/api/kiosk/history", timeout=20, params=параметры)


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

    # ---------- фото и видео в боте ----------
    def медиа(self, код):
        """Что дошло до бота по коду обмена: фото, видео, отметки диагностики.

        В базу Оценки с точки хода нет — порт Postgres закрыт наружу, — а сервер стоит на
        том же VPS и читает её. Поэтому про медиа касса спрашивает его. Не ответил или
        ответил «не знаю» — так и говорим на экране: «не вижу» это не «не прислали»."""
        res = self._req("GET", f"/api/kiosk/media/{код}", timeout=15)
        return res if isinstance(res, dict) else {"известно": False, "почему": "сервер не ответил"}

    def спросить_цену(self, код, посылка):
        """Попросить у бота автоцену до сделки. → {принято: bool, почему: str}.

        Цену считает только бот Оценки, своим прайсом; сервер передаёт ему запрос, а ответ
        приходит тем же опросом, что и медиа (`медиа(код)` → «оценка»)."""
        try:
            res = self._req("POST", f"/api/kiosk/media/{код}/quote",
                            json={"посылка": посылка}, timeout=20)
        except Exception as exc:                                 # noqa: BLE001
            return {"принято": False, "почему": f"сервер не ответил: {exc}"}
        return res if isinstance(res, dict) else {"принято": False, "почему": "сервер не ответил"}

    def напомнить_о_медиа(self, код):
        """Попросить сервер напомнить сотруднику в боте про фото и видео.
        → {отправлено: bool, почему: str}."""
        try:
            res = self._req("POST", f"/api/kiosk/media/{код}/remind", timeout=30)
        except Exception as exc:                                 # noqa: BLE001
            return {"отправлено": False, "почему": f"сервер не ответил: {exc}"}
        return res if isinstance(res, dict) else {"отправлено": False, "почему": "сервер не ответил"}

    def отправить_посылку(self, код, посылка):
        """Сделку — боту через наш сервер. → {принято: bool, почему: str, сделка: id|None}.

        Это главный путь: сервер кладёт посылку в таблицу обмена, бот забирает её оттуда
        сам и создаёт сделку — подтверждать кнопкой нечего. Сервер не ответил или отказал
        — касса уходит в запасной путь и шлёт карточку в чат, как раньше. Поэтому здесь
        не бросаем, а возвращаем причину словами."""
        try:
            res = self._req("POST", f"/api/kiosk/media/{код}/parcel",
                            json={"посылка": посылка}, timeout=30)
        except Exception as exc:                                 # noqa: BLE001
            return {"принято": False, "почему": f"сервер не ответил: {exc}"}
        if not isinstance(res, dict):
            return {"принято": False, "почему": "сервер не ответил"}
        return res

    def intake(self, ev_id):
        """Состояние заявки: номер выдаёт сотрудник в кассе (после имени и телефона клиента); ссылка на отчёт для QR."""
        return self._req("GET", f"/api/kiosk/evaluations/{ev_id}/intake", timeout=15)

    def decision(self, ev_id, kind):
        return self._req("POST", f"/api/kiosk/evaluations/{ev_id}/decision", json={"decision": kind})

    def отправить_логи(self, строки) -> int:
        """Журнал программы — на сервер. Раньше он лежал только на точке, и прочитать его
        можно было, лишь приехав туда."""
        строки = [str(x) for x in (строки or []) if str(x or "").strip()][:500]
        if not строки:
            return 0
        self._req("POST", "/api/kiosk/logs", json={"lines": строки}, timeout=30)
        return len(строки)

    def отправить_эталоны(self, папка, отметка, предел=10) -> dict:
        """Догнать сервер эталонами, которых он ещё не видел. → {ушло, осталось, ошибка}.

        Что уже ушло, помним в отметке рядом: эталон — это обезличенный слепок с сырым
        журналом Apple, по нему чинят разбор, и терять его из-за обрыва связи нельзя."""
        import glob
        отправлено = set()
        try:
            with open(отметка, encoding="utf-8") as f:
                отправлено = set(json.load(f).get("ушло") or [])
        except Exception:                                        # noqa: BLE001 — нет отметки
            pass
        файлы = [p for p in sorted(glob.glob(os.path.join(папка, "эталон_*.zip")))
                 if os.path.basename(p) not in отправлено]
        ушло, ошибка = 0, ""
        for путь in файлы[:предел]:
            try:
                with open(путь, "rb") as fh:
                    # имя эталона кириллическое, а в заголовке multipart такое не проходит:
                    # httpx кодирует заголовки в ascii. Настоящее имя шлём полем формы.
                    self._req("POST", "/api/kiosk/reference", timeout=60,
                              files={"file": ("bundle.zip", fh.read(), "application/zip")},
                              data={"name": os.path.basename(путь)})
                отправлено.add(os.path.basename(путь))
                ушло += 1
            except ServerError as e:
                ошибка = str(e)
                break
        if ушло:
            try:
                os.makedirs(os.path.dirname(отметка), exist_ok=True)
                with open(отметка, "w", encoding="utf-8") as f:
                    json.dump({"ушло": sorted(отправлено)}, f, ensure_ascii=False)
            except OSError:
                pass
        return {"ушло": ушло, "осталось": max(0, len(файлы) - ушло), "ошибка": ошибка}

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
