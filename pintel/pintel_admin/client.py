# -*- coding: utf-8 -*-
"""Запросы к серверу кассы. Единственное место, где программа ходит в сеть.

Ошибка связи — не поломка программы, а обычная жизнь: интернет моргнул, сервер
перезапускают. Поэтому наружу отдаётся понятная фраза, а не трассировка, и по ней экран
говорит человеку, что делать.
"""
from __future__ import annotations


class НетСвязи(Exception):
    """Сервер не ответил. Текст — то, что можно показать человеку."""


class НуженВход(Exception):
    """Токен не подошёл: истёк или доступ закрыли."""


class Клиент:
    def __init__(self, сервер: str, токен: str = "", таймаут: float = 20.0, транспорт=None):
        self.сервер = (сервер or "").rstrip("/")
        self.токен = токен or ""
        self.таймаут = таймаут
        self._транспорт = транспорт          # для тестов: httpx.MockTransport

    # ---------- низ ----------
    def _запрос(self, метод: str, путь: str, данные=None):
        import httpx
        заголовки = {"x-admin-token": self.токен} if self.токен else {}
        try:
            with httpx.Client(base_url=self.сервер, timeout=self.таймаут,
                              transport=self._транспорт) as с:
                ответ = с.request(метод, путь, json=данные, headers=заголовки)
        except Exception as сбой:                        # noqa: BLE001 — любая беда сети
            raise НетСвязи(f"сервер не ответил: {type(сбой).__name__}") from сбой
        if ответ.status_code in (401, 403):
            raise _отказ(ответ)
        if ответ.status_code >= 400:
            raise НетСвязи(f"сервер ответил {ответ.status_code}")
        return ответ.json()

    # ---------- вход ----------
    def войти(self, логин: str, пароль: str) -> dict:
        """→ {токен, имя, роль}. Пароль нигде не сохраняется."""
        итог = self._запрос("POST", "/api/admin/login", {"логин": логин, "пароль": пароль})
        self.токен = str(итог.get("токен") or "")
        return итог

    def выйти(self):
        try:
            self._запрос("POST", "/api/admin/logout")
        except Exception:                                # noqa: BLE001 — выходим в любом случае
            pass
        self.токен = ""

    # ---------- данные ----------
    def обзор(self) -> dict:
        return self._запрос("GET", "/api/admin/overview")

    def точки(self) -> list:
        return self._запрос("GET", "/api/admin/points").get("точки") or []

    def компьютеры(self) -> list:
        return self._запрос("GET", "/api/admin/machines").get("компьютеры") or []

    def тревоги(self, сборка: str = "") -> list:
        путь = "/api/admin/alerts" + (f"?сборка={сборка}" if сборка else "")
        return self._запрос("GET", путь).get("тревоги") or []

    def люди(self) -> list:
        return self._запрос("GET", "/api/admin/people").get("люди") or []

    def воронка(self, дней: int = 30) -> dict:
        return self._запрос("GET", f"/api/admin/funnel?дней={int(дней)}")

    def эталоны(self) -> dict:
        return self._запрос("GET", "/api/admin/references")

    # ---------- остальные разделы ----------
    def деньги(self, дней: int = 30) -> dict:
        return self._запрос("GET", f"/api/admin/money?дней={int(дней)}")

    def товар(self, дней: int = 120) -> dict:
        return self._запрос("GET", f"/api/admin/stock?дней={int(дней)}")

    def проверки(self, дней: int = 30) -> dict:
        return self._запрос("GET", f"/api/admin/checks?дней={int(дней)}")

    def сертификаты(self, дней: int = 30) -> dict:
        return self._запрос("GET", f"/api/admin/certificates?дней={int(дней)}")

    def эталоны_списком(self) -> dict:
        return self._запрос("GET", "/api/admin/reference-list")

    def телефон(self, запрос: str) -> dict:
        from urllib.parse import quote
        return self._запрос("GET", f"/api/admin/phone?q={quote(запрос or '')}")

    def журнал(self) -> list:
        return self._запрос("GET", "/api/admin/audit").get("журнал") or []

    def роли(self) -> dict:
        return self._запрос("GET", "/api/admin/roles")

    def чёрный_список(self) -> list:
        return self._запрос("GET", "/api/admin/blacklist").get("записи") or []

    def чёрный_добавить(self, imei: str, почему: str) -> list:
        return self._запрос("POST", "/api/admin/blacklist",
                            {"imei": imei, "почему": почему}).get("записи") or []

    def чёрный_убрать(self, imei: str) -> list:
        from urllib.parse import quote
        return self._запрос("DELETE", f"/api/admin/blacklist/{quote(str(imei))}").get("записи") or []


def _отказ(ответ):
    """401 и 403 — разные разговоры с человеком: «войдите заново» и «вам сюда нельзя»."""
    if ответ.status_code == 403:
        return НетСвязи("этой учётной записи сюда нельзя: нужна роль администратора")
    return НуженВход("нужно войти заново")
