# -*- coding: utf-8 -*-
"""Верификация IMEI: строковые поля → справочник (верифицирован / не верифицирован / заблокирован).

    python3.13 ms_rfs_fields.py <.env бота> show     # что есть сейчас
    python3.13 ms_rfs_fields.py <.env бота> снимок   # сохранить значения всех карточек
    python3.13 ms_rfs_fields.py <.env бота> обмен    # завести справочник и поменять поля
    python3.13 ms_rfs_fields.py <.env бота> вернуть  # вписать сохранённые значения обратно

Владелец, 23.11.2026: «переделай существующие поля под галочки или же переменные
(вериф/невериф/заблок)». Тип доп. поля в МойСкладе не меняется — поле можно только удалить и
завести заново. Поэтому порядок строгий и разбит на шаги: сначала снимок, потом обмен, потом
возврат значений. Снимок делается ДО удаления и лежит файлом рядом; без него шаг «обмен»
отказывается работать.

Что теряется: при удалении поля МойСклад стирает его значения во всех карточках. На
23.11.2026 заполнено 158 карточек из 9100. Шаг «вернуть» вписывает их обратно — кроме
«Неизвестно»: реестр не ответил, и поле честнее оставить пустым, чем писать слово, которое
читается как приговор.

Новые поля встают в КОНЕЦ карточки: порядок полей в МойСкладе — это порядок их создания,
переставить через API нельзя.
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request

BASE = "https://api.moysklad.ru/api/remap/1.2"
ПОЛЯ = ("Верификация IMEI 1", "Верификация IMEI 2")
СПРАВОЧНИК = "Верификация IMEI"
ЗНАЧЕНИЯ = ("Верифицирован", "Не верифицирован", "Заблокирован")
СНИМОК = "/root/rfs_values.json"


def ключ_из_env(путь):
    for строка in open(путь, encoding="utf-8", errors="replace"):
        строка = строка.strip()
        if строка.startswith("API_KEY_SKLAD"):
            return строка.split("=", 1)[1].strip().strip('"').strip("'")
    sys.exit(f"в {путь} нет API_KEY_SKLAD")


def запрос(ключ, метод, путь, тело=None):
    данные = json.dumps(тело).encode() if тело is not None else None
    req = urllib.request.Request(
        путь if путь.startswith("http") else BASE + путь, data=данные, method=метод,
        headers={"Authorization": "Bearer " + ключ, "Accept-Encoding": "gzip",
                 "Accept": "application/json;charset=utf-8", "Content-Type": "application/json"})
    for попытка in range(4):
        try:
            with urllib.request.urlopen(req, timeout=90) as о:
                тело_ответа = о.read()
                if о.headers.get("Content-Encoding") == "gzip":
                    import gzip
                    тело_ответа = gzip.decompress(тело_ответа)
                return json.loads(тело_ответа) if тело_ответа else {}
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503, 504) and попытка < 3:
                time.sleep(0.7 * (2 ** попытка))
                continue
            sys.exit(f"HTTP {e.code} {метод} {путь}: {e.read()[:300]!r}")
        except urllib.error.URLError:
            if попытка < 3:
                time.sleep(0.7 * (2 ** попытка))
                continue
            raise


def поля_карточки(ключ):
    строки = запрос(ключ, "GET", "/entity/product/metadata/attributes").get("rows") or []
    return {(a.get("name") or "").strip(): a for a in строки}


def все_товары(ключ):
    сдвиг = 0
    while True:
        о = запрос(ключ, "GET", f"/entity/product?limit=100&offset={сдвиг}")
        строки = о.get("rows") or []
        if not строки:
            return
        for т in строки:
            yield т
        сдвиг += 100
        if сдвиг >= (о.get("meta") or {}).get("size", 0):
            return


def снять_снимок(ключ):
    """Что сейчас стоит в полях верификации. → сколько карточек сохранили."""
    собрано = []
    for т in все_товары(ключ):
        свои = {}
        for a in т.get("attributes") or []:
            имя = (a.get("name") or "").strip()
            if имя in ПОЛЯ:
                v = a.get("value")
                v = v.get("name") if isinstance(v, dict) else v
                if str(v or "").strip():
                    свои[имя] = str(v).strip()
        if свои:
            собрано.append({"id": т["id"], "код": т.get("code"), "значения": свои})
    with open(СНИМОК, "w", encoding="utf-8") as f:
        json.dump(собрано, f, ensure_ascii=False, indent=1)
    return len(собрано)


ПАМЯТКА = "/root/rfs_dict_id.txt"       # id справочника: списка всех справочников в API нет


def _номер_из_ссылки(href):
    части = [ч for ч in str(href or "").rstrip("/").split("/") if ч]
    return части[части.index("customentity") + 1] if "customentity" in части else ""


def справочник(ключ):
    """Найти или завести справочник и его значения. → (id справочника, {значение: meta}).

    Списка всех справочников МойСклад не отдаёт (`GET /entity/customentity` — 400), поэтому
    ищем так: сперва по нашим же полям, если они уже справочниками; затем по записке с
    прошлого запуска; и только потом заводим новый."""
    cid = ""
    for поле in поля_карточки(ключ).values():
        if (поле.get("name") or "").strip() in ПОЛЯ and поле.get("type") == "customentity":
            cem = поле.get("customEntityMeta") or {}
            cid = _номер_из_ссылки(cem.get("href") or (cem.get("meta") or {}).get("href"))
            if cid:
                break
    if not cid and os.path.exists(ПАМЯТКА):
        cid = open(ПАМЯТКА, encoding="utf-8").read().strip()
    if not cid:
        свой = запрос(ключ, "POST", "/entity/customentity", {"name": СПРАВОЧНИК})
        cid = свой["id"]
        with open(ПАМЯТКА, "w", encoding="utf-8") as f:
            f.write(cid)
        print(f"   заведён справочник «{СПРАВОЧНИК}»")
    строки = запрос(ключ, "GET", f"/entity/customentity/{cid}?limit=100").get("rows") or []
    по_имени = {(с.get("name") or "").strip(): с for с in строки}
    for значение in ЗНАЧЕНИЯ:
        if значение not in по_имени:
            по_имени[значение] = запрос(ключ, "POST", f"/entity/customentity/{cid}",
                                        {"name": значение})
            print(f"   добавлено значение «{значение}»")
    return cid, {и: с["meta"] for и, с in по_имени.items()}


def обмен(ключ):
    if not os.path.exists(СНИМОК):
        sys.exit(f"СТОП: сначала снимок — нет файла {СНИМОК}")
    cid, _ = справочник(ключ)
    есть = поля_карточки(ключ)
    for имя in ПОЛЯ:
        поле = есть.get(имя)
        if поле is None:
            print(f"   поля «{имя}» нет — создаю")
        elif (поле.get("type") or "") == "customentity":
            print(f"   «{имя}» уже справочник — пропускаю")
            continue
        else:
            запрос(ключ, "DELETE", f"/entity/product/metadata/attributes/{поле['id']}")
            print(f"   удалено прежнее «{имя}» (было {поле.get('type')})")
        запрос(ключ, "POST", "/entity/product/metadata/attributes", {
            "name": имя, "type": "customentity", "required": False,
            "customEntityMeta": {
                "href": f"{BASE}/entity/customentity/{cid}/metadata",
                "type": "customentitymetadata", "mediaType": "application/json"}})
        print(f"   создано «{имя}» справочником")


def вернуть(ключ):
    if not os.path.exists(СНИМОК):
        sys.exit(f"СТОП: нет файла {СНИМОК} — возвращать нечего")
    with open(СНИМОК, encoding="utf-8") as f:
        снимок = json.load(f)
    _cid, meta = справочник(ключ)
    поля = поля_карточки(ключ)
    вернули, пропущено = 0, {}
    for запись in снимок:
        атрибуты = []
        for имя, значение in (запись.get("значения") or {}).items():
            поле = поля.get(имя)
            if поле is None or значение not in meta:
                пропущено[значение] = пропущено.get(значение, 0) + 1
                continue
            атрибуты.append({"meta": поле["meta"], "value": {"meta": meta[значение]}})
        if not атрибуты:
            continue
        запрос(ключ, "PUT", f"/entity/product/{запись['id']}", {"attributes": атрибуты})
        вернули += 1
        if вернули % 20 == 0:
            print(f"   вернули {вернули}…")
    print(f"вернули значений в карточках: {вернули}")
    for значение, сколько in пропущено.items():
        print(f"   не возвращено «{значение}»: {сколько} (в справочнике такого нет — "
              f"поле осталось пустым)")


def main():
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    env, команда = sys.argv[1], sys.argv[2]
    ключ = ключ_из_env(env)
    if команда == "show":
        есть = поля_карточки(ключ)
        for имя in ПОЛЯ:
            поле = есть.get(имя)
            print(f"{имя}: {поле.get('type') if поле else 'НЕТ ПОЛЯ'}")
        if os.path.exists(СНИМОК):
            with open(СНИМОК, encoding="utf-8") as f:
                print(f"снимок: {len(json.load(f))} карточек ({СНИМОК})")
        else:
            print("снимка нет")
    elif команда == "снимок":
        print("карточек со значениями сохранено:", снять_снимок(ключ))
    elif команда == "обмен":
        обмен(ключ)
    elif команда == "вернуть":
        вернуть(ключ)
    else:
        sys.exit("команда: show | снимок | обмен | вернуть")


if __name__ == "__main__":
    main()
