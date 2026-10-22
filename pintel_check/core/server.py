"""Локальный сервер. Только стандартная библиотека — значит упаковка в exe
не тянет зависимостей и ломаться нечему.

Интерфейс открывается в браузере на 127.0.0.1. Это же решает второй этап:
проверки экрана, тача и камер всё равно идут через браузер телефона.
"""
import json, os, threading, traceback
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

from . import apple, device, price, setup, sickw, store, verdict

WEB = os.path.join(os.path.dirname(__file__), "..", "web")
# Долгие операции (ожидание вердикта Apple до 60 с) считаем в фоне и
# отдаём состояние опросом — иначе браузер отвалится по таймауту.
JOBS = {}


def _job(name, fn):
    JOBS[name] = {"готово": False, "ошибка": None, "результат": None}
    def run():
        try:
            JOBS[name]["результат"] = fn()
        except Exception as e:
            JOBS[name]["ошибка"] = f"{type(e).__name__}: {e}"
            JOBS[name]["трасса"] = traceback.format_exc()
        finally:
            JOBS[name]["готово"] = True
    threading.Thread(target=run, daemon=True).start()


class H(SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=WEB, **kw)

    def log_message(self, *a):
        pass          # не засоряем консоль приёмщика

    def _send(self, obj, code=200):
        b = json.dumps(obj, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        if not n:
            return {}
        try:
            return json.loads(self.rfile.read(n).decode("utf-8"))
        except Exception:
            return {}

    # ---------------- GET ----------------
    def do_GET(self):
        u = urlparse(self.path)
        q = parse_qs(u.query)
        try:
            if u.path == "/api/device":
                try:
                    return self._send({"подключён": True, "udid": device.udid()})
                except device.NoDevice as e:
                    return self._send({"подключён": False, "почему": str(e)})
            if u.path == "/api/job":
                name = q.get("name", [""])[0]
                return self._send(JOBS.get(name) or {"готово": False, "ошибка": "нет такой задачи"})
            if u.path == "/api/check":
                r = store.get(int(q.get("id", ["0"])[0]))
                if not r:
                    return self._send({"ошибка": "не найдено"}, 404)
                for k in ("кабель", "apple", "sickw", "этап2", "этап3"):
                    if r.get(k):
                        try:
                            r[k] = json.loads(r[k])
                        except Exception:
                            pass
                return self._send(r)
            if u.path == "/api/checks":
                return self._send({"список": store.recent()})
            if u.path == "/api/setup":
                return self._send(setup.check())
            if u.path == "/api/config":
                return self._send({"sickw_ключ": sickw.key_available(),
                                   "sickw_ключ_хвост": sickw.key_tail(),
                                   "прайс": price.load()})
        except Exception as e:
            return self._send({"ошибка": f"{type(e).__name__}: {e}"}, 500)
        return super().do_GET()

    # ---------------- POST ----------------
    def do_POST(self):
        u = urlparse(self.path)
        b = self._body()
        try:
            # --- ЭТАП 1: кабель -> вердикты -> предварительная цена ---
            if u.path == "/api/stage1":
                def work():
                    raw = device.collect()
                    res = verdict.build(raw)
                    cid = store.create(raw["udid"], res, raw)
                    est = price.estimate(res)
                    store.update(cid, цена=est["итого"] or 0)
                    return {"id": cid, "вердикты": res, "оценка": est}
                _job("stage1", work)
                return self._send({"запущено": "stage1"})

            # --- вердикт Apple: нужен переход в раздел на телефоне ---
            if u.path == "/api/apple":
                cid = int(b.get("id") or 0)
                def work():
                    u_ = device.udid()
                    items, _ = apple.capture(u_, seconds=int(b.get("seconds") or 60))
                    if cid and items:
                        store.update(cid, apple=items)
                    return {"детали": items}
                _job("apple", work)
                return self._send({"запущено": "apple"})

            # --- внешняя база: платный запрос, поэтому только по команде ---
            if u.path == "/api/sickw":
                cid = int(b.get("id") or 0)
                imei = str(b.get("imei") or "")
                def work():
                    s = sickw.lookup(imei)
                    if cid:
                        store.update(cid, sickw=s)
                    return s
                _job("sickw", work)
                return self._send({"запущено": "sickw"})

            # --- пересчёт цены со всем, что уже известно ---
            if u.path == "/api/price":
                cid = int(b.get("id") or 0)
                r = store.get(cid)
                if not r:
                    return self._send({"ошибка": "не найдено"}, 404)
                res = json.loads(r["кабель"])["вердикты"]
                sk = json.loads(r["sickw"]) if r.get("sickw") else None
                ap = json.loads(r["apple"]) if r.get("apple") else None
                est = price.estimate(res, sk, ap)
                store.update(cid, цена=est["итого"] or 0)
                return self._send({"оценка": est})

            # --- настройки: ключ Sickw ---
            if u.path == "/api/settings":
                if "sickw_key" in b:
                    sickw.save_key(str(b.get("sickw_key") or ""))
                return self._send({"сохранено": True,
                                   "sickw_ключ": sickw.key_available(),
                                   "sickw_ключ_хвост": sickw.key_tail()})

            # --- ЭТАП 2: ручные проверки ---
            if u.path == "/api/stage2":
                cid = int(b.get("id") or 0)
                store.update(cid, этап=2, этап2=b.get("результаты") or {})
                return self._send({"сохранено": True})

            # --- ЭТАП 3: финал ---
            if u.path == "/api/stage3":
                cid = int(b.get("id") or 0)
                store.update(cid, этап=3, этап3=b.get("данные") or {})
                return self._send({"сохранено": True})
        except Exception as e:
            return self._send({"ошибка": f"{type(e).__name__}: {e}",
                               "трасса": traceback.format_exc()}, 500)
        return self._send({"ошибка": "неизвестный путь"}, 404)


def serve(port=8765):
    srv = ThreadingHTTPServer(("127.0.0.1", port), H)
    return srv
