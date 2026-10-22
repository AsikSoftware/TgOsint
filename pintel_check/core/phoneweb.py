# -*- coding: utf-8 -*-
"""Мини-сервер теста на телефоне клиента.

Киоск показывает QR → iPhone открывает страницу по Wi-Fi той же сети →
телефон сам прогоняет тесты (тач-сетка, мультитач, экран, звук) и
отправляет результат обратно. Никакой установки: iOS не пускает сторонние
приложения на чужой телефон, а веб-страница делает то же самое мгновенно.

Токен одноразовый, на одну приёмку: чужое устройство из сети не сможет
подбросить результат в чужую сессию.
"""
import json, socket, threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .paths import bundled

_lock = threading.Lock()
_state = {"token": None, "cb": None}


def set_session(token, cb):
    with _lock:
        _state["token"], _state["cb"] = token, cb


def clear():
    with _lock:
        _state["token"], _state["cb"] = None, None


def lan_ip():
    """IP этого компьютера в локальной сети — его видит телефон."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        s.close()


class _H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.startswith("/t/"):
            try:
                page = open(bundled("phone", "diag.html"), "rb").read()
            except Exception:
                return self._send(500, "нет страницы теста".encode(), "text/plain; charset=utf-8")
            return self._send(200, page, "text/html; charset=utf-8")
        if self.path == "/ping":
            return self._send(200, b'{"ok": true}')
        return self._send(404, b'{"error": "not found"}')

    def do_POST(self):
        if not self.path.startswith("/api/phone/"):
            return self._send(404, b'{"error": "not found"}')
        token = self.path.rsplit("/", 1)[-1]
        n = int(self.headers.get("Content-Length") or 0)
        try:
            data = json.loads(self.rfile.read(n).decode("utf-8")) if n else {}
        except Exception:
            data = {}
        with _lock:
            ok = _state["token"] and token == _state["token"]
            cb = _state["cb"] if ok else None
        if not cb:
            return self._send(410, json.dumps(
                {"ошибка": "приёмка уже закрыта"}, ensure_ascii=False).encode())
        try:
            cb(data)
        except Exception:
            pass
        return self._send(200, json.dumps({"принято": True},
                                          ensure_ascii=False).encode())


def start(port=8765):
    """Поднимает сервер на всех интерфейсах. Возвращает server или None."""
    try:
        srv = ThreadingHTTPServer(("0.0.0.0", port), _H)
    except OSError:
        return None
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv
