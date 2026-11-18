# -*- coding: utf-8 -*-
"""Бот Оценки: повторять запрос к МойСкладу не только при 429.

    python3.13 ms_retry_patch.py <каталог бота> --check    # только проверить, ляжет ли
    python3.13 ms_retry_patch.py <каталог бота>            # поставить

Сначала положить рядом модуль: `cp ms_http.py <каталог бота>/utils/`.

Зачем. `_ms_request` в `utils/ms_prihod_importer.py` — единственная дверь в МойСклад для всего
бота: через него ходят и автоприёмка при выкупе, и приход из Excel, и режим обновления кассы.
Повтор в нём был ровно один — при 429 (лимит запросов). Любой другой отказ падал с первой
попытки, и каждый раз это стоило данных:

* 18.11.2026, 12:27 Алматы: МойСклад ответил `503` на чтение справочника «Статус» — и
  автоприёмка завела карточку товара БЕЗ состояния. В журнале одна строка «доп. поле Статус
  пропущено», сотруднику ничего, карточка осталась неполной;
* тот же отказ на `POST /entity/supply` рвёт приёмку целиком;
* в приходе из Excel человек видит отказ и грузит файл заново.

Что меняется. `_ms_request` отдаёт повторы в `utils/ms_http.py`, прежняя функция остаётся
рядом под именем `_ms_request_legacy` и работает, если модуль не загрузился: ходить в
МойСклад важнее, чем повторять. Политика повтора — в самом модуле, коротко:

* 429 — как было, по `Retry-After`;
* 5xx — повторяем любой запрос, включая POST: сервер ответил «не могу», значит не выполнил;
* обрыв связи (ответа нет вовсе) — только GET и PUT. POST не повторяем никогда: неизвестно,
  создался документ или нет, и повтор завёл бы двойника.

Проверено тестами без сети: tests/test_ms_http.py (16 проверок).

Замена обязана лечь ровно один раз, иначе скрипт останавливается, ничего не записав.
Рядом кладётся копия `<файл>.bak_<дата>`.
"""
import datetime
import io
import os
import sys

root = sys.argv[1].rstrip("/")
ТОЛЬКО_ПРОВЕРКА = "--check" in sys.argv
_файлы = {}

ФАЙЛ = "/utils/ms_prihod_importer.py"


def читать(p):
    if p not in _файлы:
        _файлы[p] = io.open(root + p, encoding="utf-8").read()
    return _файлы[p]


def patch(p, pairs, раз=1):
    s = читать(p)
    for old, new in pairs:
        if s.count(old) != раз:
            sys.exit(f"СТОП, ничего не записано: {p} — замена должна лечь {раз} раз(а), "
                     f"а легла бы {s.count(old)}: {old[:70]!r}")
        s = s.replace(old, new)
    _файлы[p] = s


if not os.path.exists(root + "/utils/ms_http.py"):
    sys.exit("СТОП: сначала положите модуль — cp ms_http.py " + root + "/utils/")
if "ms_http" in читать(ФАЙЛ):
    sys.exit("уже стоит: _ms_request отдаёт повторы в ms_http — ничего не делаю")

patch(ФАЙЛ, [
    ('''def _ms_request(session: requests.Session, method: str, path_or_url: str, params=None, body=None):
    url = path_or_url if path_or_url.startswith("http") else f"{BASE_URL}{path_or_url}"

    for attempt in range(MS_RATE_RETRIES):''',
     '''def _ms_request(session: requests.Session, method: str, path_or_url: str, params=None, body=None):
    """Запрос к МойСкладу. Повторы — в utils/ms_http.py: 429, 5xx и обрыв связи, и только
    там, где повтор не создаёт двойника (POST после обрыва не повторяется). Модуль не
    загрузился — ходим как прежде, с повтором одного лишь 429: связь важнее повторов."""
    url = path_or_url if path_or_url.startswith("http") else f"{BASE_URL}{path_or_url}"
    try:
        from utils import ms_http
    except Exception:                                                # noqa: BLE001
        return _ms_request_legacy(session, method, url, params=params, body=body)
    return ms_http.запросить(
        lambda: session.request(method, url, params=params, json=body, timeout=60),
        method, url, обрыв=requests.exceptions.RequestException,
        перед=_ms_throttle, журнал=logger)


def _ms_request_legacy(session: requests.Session, method: str, path_or_url: str, params=None, body=None):
    url = path_or_url if path_or_url.startswith("http") else f"{BASE_URL}{path_or_url}"

    for attempt in range(MS_RATE_RETRIES):'''),
])

for p, s in _файлы.items():
    compile(s, root + p, "exec")
изменённые = [p for p, s in _файлы.items() if s != io.open(root + p, encoding="utf-8").read()]
if ТОЛЬКО_ПРОВЕРКА:
    print("проверка: замена ложится, изменится файлов:", len(изменённые))
    sys.exit(0)
метка = datetime.datetime.now().strftime("%Y-%m-%d_%H%M")
for p in изменённые:
    with open(root + p, "rb") as f:
        прежнее = f.read()
    with open(root + p + ".bak_" + метка, "wb") as f:
        f.write(прежнее)
    io.open(root + p, "w", encoding="utf-8", newline="\n").write(_файлы[p])
    print("записан", p, "(копия .bak_" + метка + ")")
print("готово. Дальше: проверить импорт (python3 -c 'from utils import ms_prihod_importer') "
      "и перезапустить бота.")
