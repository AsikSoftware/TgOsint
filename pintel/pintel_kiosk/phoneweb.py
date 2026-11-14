# -*- coding: utf-8 -*-
"""Мини-сервер теста на телефоне клиента.

Киоск показывает QR → телефон клиента открывает страницу по Wi-Fi той же сети → телефон
сам прогоняет тесты (сенсор, мультитач, экран, динамик, микрофон, обе камеры) и отправляет
результат обратно в киоск. Страница — `assets/diag.html`, словарь тестов —
`pintel_core.phonetest`.

Почему мини-сервер в самом киоске, а не страница на нашем сервере:

* ставить приложение на чужой телефон нельзя (iOS не пускает), а страница открывается сразу;
* **работает без интернета.** Шаг обязательный, а значит он не может зависеть от сети, от
  домена и от сервера, который мы больше не держим: нужен только общий Wi-Fi с кассой.

Токен одноразовый, на одну сделку: другое устройство из той же сети не подбросит результат в
чужую сделку. Больше ничего сервер не отдаёт — ни файлов, ни каталогов.
"""
from __future__ import annotations

import json
import os
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ПОРТ = 8765
ПРЕДЕЛ_ТЕЛА = 64 * 1024              # результат теста — это семь коротких строк
# Страница лежит в pintel_core: её отдаёт и этот мини-сервер, и наш сервер на домене
# (pintel_server), когда точка работает с ним. Одна страница на оба пути — иначе они
# разойдутся, и тест на домене начнёт спрашивать не то, что тест в локальной сети.
from pintel_core import phonetest                                   # noqa: E402

СТРАНИЦА = phonetest.СТРАНИЦА_ФАЙЛ

_замок = threading.Lock()
_сессия = {"токены": (), "приёмник": None}
_сервер = None                       # один на процесс: порт один, окон киоска тоже одно


def открыть(токен: str, приёмник, ещё=()) -> None:
    """Начать сессию: этот токен принимаем, результат отдадим в `приёмник(данные)`.

    `ещё` — прежние коды ЭТОЙ ЖЕ сделки. «Другой код» их не отменяет: клиент мог уже
    открыть страницу по прошлому QR, и пройденный на ней тест терять нельзя. Коды чужих
    сделок сюда не попадают — сессию заводят заново с каждой сделкой."""
    with _замок:
        _сессия["токены"] = tuple(x for x in (токен, *(ещё or ())) if x)
        _сессия["приёмник"] = приёмник


def закрыть() -> None:
    with _замок:
        _сессия["токены"], _сессия["приёмник"] = (), None


def адрес_в_сети() -> str:
    """IP этого компьютера в локальной сети — его видит телефон клиента."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))                   # соединение не устанавливается, адрес уже известен
        return s.getsockname()[0]
    except Exception:                                # noqa: BLE001 — сети нет вовсе
        return ""
    finally:
        s.close()


def ссылка(токен: str, порт: int = ПОРТ, ip: str = "") -> str:
    """Адрес страницы теста для QR. Пусто — сети нет, показывать нечего."""
    ip = ip or адрес_в_сети()
    return f"http://{ip}:{порт}/t/{токен}" if ip and токен else ""


class _Обработчик(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):                       # в журнал киоска пишем сами, а не в stderr
        pass

    def _ответ(self, код, тело, тип="application/json; charset=utf-8"):
        if isinstance(тело, str):
            тело = тело.encode("utf-8")
        self.send_response(код)
        self.send_header("Content-Type", тип)
        self.send_header("Content-Length", str(len(тело)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            self.wfile.write(тело)
        except Exception:                            # noqa: BLE001 — телефон ушёл из сети
            pass

    def do_GET(self):
        if self.path.startswith("/t/"):
            with _замок:
                токены = _сессия["токены"]
            if self.path.rsplit("/", 1)[-1] not in токены:
                return self._ответ(410, "Эта проверка уже закончена. Возьмите новый код у продавца.",
                                   "text/plain; charset=utf-8")
            try:
                with open(СТРАНИЦА, "rb") as f:
                    страница = f.read()
            except Exception:                        # noqa: BLE001 — страницы нет в сборке
                return self._ответ(500, "Страница теста не найдена, скажите продавцу.",
                                   "text/plain; charset=utf-8")
            return self._ответ(200, страница, "text/html; charset=utf-8")
        if self.path == "/ping":
            return self._ответ(200, '{"ok": true}')
        return self._ответ(404, "Pintel. Откройте ссылку с экрана кассы.",
                           "text/plain; charset=utf-8")

    def do_POST(self):
        if not self.path.startswith("/api/phone/"):
            return self._ответ(404, '{"error": "not found"}')
        токен_запроса = self.path.rsplit("/", 1)[-1]
        длина = int(self.headers.get("Content-Length") or 0)
        if длина > ПРЕДЕЛ_ТЕЛА:
            # тело надо вычитать или оборвать соединение: иначе телефон продолжает отправку и
            # получает «connection reset» вместо нашего ответа, а сотрудник — «нет связи»
            self.close_connection = True
            try:
                self.rfile.read(min(длина, 1024 * 1024))
            except Exception:                        # noqa: BLE001
                pass
            return self._ответ(413, '{"error": "too large"}')
        try:
            данные = json.loads(self.rfile.read(длина).decode("utf-8")) if длина else {}
        except Exception:                            # noqa: BLE001
            данные = {}
        with _замок:
            свой = bool(токен_запроса) and токен_запроса in _сессия["токены"]
            приёмник = _сессия["приёмник"] if свой else None
        if приёмник is None:
            return self._ответ(410, json.dumps({"ошибка": "проверка уже закрыта"},
                                               ensure_ascii=False))
        try:
            приёмник(данные)
        except Exception:                            # noqa: BLE001 — киоск ответит сам
            return self._ответ(500, json.dumps({"ошибка": "касса не приняла"}, ensure_ascii=False))
        return self._ответ(200, json.dumps({"принято": True}, ensure_ascii=False))


def запустить(порт: int = ПОРТ):
    """Поднять сервер на всех интерфейсах. → сервер или None, если порт занят.

    Второй раз в том же процессе возвращаем уже поднятый: порт один, и повторный запуск
    отдал бы None — то есть окно решило бы, что теста на телефоне не будет."""
    global _сервер
    if _сервер is not None:
        return _сервер
    try:
        сервер = ThreadingHTTPServer(("0.0.0.0", порт), _Обработчик)
    except OSError:
        return None
    сервер.daemon_threads = True
    threading.Thread(target=сервер.serve_forever, daemon=True, name="phoneweb").start()
    _сервер = сервер
    return сервер


def остановить() -> None:
    """Только для тестов и для закрытия программы: обычно сервер живёт, пока живёт киоск."""
    global _сервер
    закрыть()
    if _сервер is not None:
        _сервер.shutdown()
        _сервер.server_close()
        _сервер = None
