# -*- coding: utf-8 -*-
"""Полный сырой слепок телефона с качеством чтения.

Что внутри:
  root        — корневой домен lockdown (паспорт)
  domains     — все домены из DOMAINS (что ответило)
  node_names  — карта всех узлов IORegistry (имена) — чтобы не угадывать
  nodes       — нужные узлы целиком (батарея, камера, NVMe, …)
  nand_summary — разбор NANDInfo и сверка прошивки с NVMe
  quality     — повторы, устаревшие первые чтения, тайминги, что не прочиталось

Двойное чтение: disk_usage читается дважды с паузой; если второй снимок
отличается — берём второй и помечаем «первое чтение устарело».
"""
import asyncio, base64, json, time
from datetime import datetime

from . import jailbreak, mdm, mobilegestalt as mg_mod, nand, panic
from .nodes import (CAMERA_FALLBACK, CAMERA_RE, DOMAINS, FIXED_NODES, MG_KEYS, MG_KEYS_COLOUR,
                    NVME_FALLBACK, NVME_RE, OPTIONAL_CLASSES, OPTIONAL_NODES, PROX_FALLBACK, PROX_RE,
                    collect_entry_names, deep, num, pick_names, txt)

SNAPSHOT_VERSION = 4      # 4: + отчёты о панике ядра (panic full)
#                           3: планы IOService/IODeviceTree, доп. узлы, MobileGestalt, джейлбрейк


class _Enc(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, (bytes, bytearray)):
            return {"__b64__": base64.b64encode(bytes(o)).decode("ascii")}
        if isinstance(o, datetime):
            return o.isoformat()
        return str(o)


def dumps(obj):
    return json.dumps(obj, cls=_Enc, ensure_ascii=False, indent=1)


def _dec(o):
    if isinstance(o, dict) and set(o) == {"__b64__"}:
        return base64.b64decode(o["__b64__"])
    return o


def loads(text):
    return json.loads(text, object_hook=_dec)


async def _retry(fn, name, quality, tries=3, delays=(0.7, 1.5, 2.5)):
    last = None
    for i in range(tries):
        try:
            r = await fn()
            if r:
                if i:
                    quality["повторы"][name] = i + 1
                return r
            last = "пусто"
        except Exception as e:
            last = f"{type(e).__name__}: {e}"
        await asyncio.sleep(delays[min(i, len(delays) - 1)])
    quality["не_прочиталось"][name] = str(last)
    return None


def _nand_stamp(dom):
    blob = (dom or {}).get("NANDInfo")
    if not blob:
        return None
    recs, _ = nand.parse(blob)
    return recs.get(0x039, [None])[0]


async def collect(ld, diag, log=lambda *a: None):
    t0 = time.monotonic()
    quality = {"повторы": {}, "не_прочиталось": {}, "устарело": [], "время_с": {}}

    log("паспорт…")
    root = await _retry(lambda: ld.get_value(), "root", quality) or {}
    quality["время_с"]["паспорт"] = round(time.monotonic() - t0, 2)

    log("домены…")
    t = time.monotonic()
    domains = {}
    for dom in DOMAINS:
        try:
            v = await ld.get_value(domain=dom)
            if v:
                domains[dom] = v
        except Exception as e:
            quality["не_прочиталось"][dom] = f"{type(e).__name__}: {e}"
    quality["время_с"]["домены"] = round(time.monotonic() - t, 2)

    # Двойное чтение disk_usage: первый снимок бывает устаревшим
    first = domains.get("com.apple.disk_usage") or {}
    await asyncio.sleep(1.5)
    try:
        second = await ld.get_value(domain="com.apple.disk_usage") or {}
    except Exception:
        second = {}
    if second:
        changed = []
        cap = num(first.get("TotalDataCapacity")) or 0
        for k in ("TotalDataAvailable", "TotalDataCapacity"):
            a, b = num(first.get(k)) or 0, num(second.get(k)) or 0
            # свободное место гуляет на сотни МБ само по себе — устаревшим считаем сдвиг > 1 %
            if a != b and (k != "TotalDataAvailable" or not cap or abs(a - b) > cap * 0.01):
                changed.append(k)
        if _nand_stamp(first) != _nand_stamp(second):
            changed.append("NANDInfo/0x039")
        if changed:
            quality["устарело"].append({"disk_usage": changed})
        domains["com.apple.disk_usage"] = second

    log("карта узлов…")
    t = time.monotonic()
    tree = await _retry(lambda: diag.ioregistry(plane="IOService"), "ioreg:IOService", quality)
    names = collect_entry_names(tree) if tree else set()
    quality["время_с"]["карта"] = round(time.monotonic() - t, 2)
    quality["узлов_в_карте"] = len(names)

    # Дерево устройств целиком: все *-serial-num, device-colors, wifi-module-sn
    # любой модели попадают в слепок, даже если мы о них ещё не знаем.
    log("дерево устройств…")
    t = time.monotonic()
    dtree = await _retry(lambda: diag.ioregistry(plane="IODeviceTree"), "ioreg:IODeviceTree", quality, tries=2)
    quality["время_с"]["дерево"] = round(time.monotonic() - t, 2)
    names_all = set(names) | (collect_entry_names(dtree) if dtree else set())

    cam_names = pick_names(names, CAMERA_RE, CAMERA_FALLBACK)
    nvme_names = pick_names(names, NVME_RE, NVME_FALLBACK)

    log("узлы…")
    t = time.monotonic()
    nodes = {}
    quality["нет_в_карте"] = []
    for name in FIXED_NODES:
        # Драйверных узлов, которых нет в карте телефона, не ждём по 5 секунд:
        # у iPhone 17 Pro нет AIDBus (USB-C) — это не сбой чтения, а устройство другое.
        if names_all and name[0].isupper() and name not in names_all:
            nodes[name] = None
            quality["нет_в_карте"].append(name)
            continue
        nodes[name] = await _retry(lambda n=name: diag.ioregistry(name=n), name, quality)
    nodes["prox"] = None
    for n in pick_names(names_all, PROX_RE, PROX_FALLBACK):
        if names_all and n not in names_all:
            continue
        v = await _retry(lambda n=n: diag.ioregistry(name=n), n, quality, tries=2)
        if v:
            nodes["prox"] = v
            quality["prox_узел"] = n
            break
    for key, cands in (("camera", cam_names), ("nvme", nvme_names)):
        nodes[key] = None
        for n in cands:
            v = await _retry(lambda n=n: diag.ioregistry(name=n), n, quality, tries=2)
            if v:
                nodes[key] = v
                quality[f"{key}_узел"] = n
                break
    # узлы «по возможности» — одна попытка, отсутствие не считается ошибкой чтения
    for key, (rx, fallback) in OPTIONAL_NODES.items():
        nodes[key] = None
        for n in pick_names(names_all, rx, fallback):
            if names_all and n not in names_all:
                continue
            try:
                v = await diag.ioregistry(name=n)
            except Exception:
                v = None
            if v:
                nodes[key] = v
                quality[f"{key}_узел"] = n
                break
    for key, cls in OPTIONAL_CLASSES.items():
        try:
            nodes[key] = await diag.ioregistry(ioclass=cls) or None
        except Exception:
            nodes[key] = None
    quality["время_с"]["узлы"] = round(time.monotonic() - t, 2)

    # MobileGestalt — лучшим доступным каналом: diagnostics до iOS 17.4, а на 17.4+
    # через userspace-туннель CoreDevice (без прав администратора; тот же канал, что у
    # 3uTools). Печать деталей, серийники модулей, цвета корпуса — без действий клиента.
    log("MobileGestalt…")
    t = time.monotonic()
    serial = txt((root or {}).get("UniqueDeviceID")) or None
    try:
        mg_res = await mg_mod.read(diag, serial=serial)
    except Exception as e:                                        # noqa: BLE001
        mg_res = {"значения": {}, "канал": "нет", "ошибка": f"{type(e).__name__}: {str(e)[:160]}"}
    mg = dict(mg_res.get("значения") or {})
    if not mg:
        mg = {"недоступен": mg_res.get("ошибка") or "пусто"}
    mg["_канал"] = mg_res.get("канал")
    if mg_res.get("device_info"):
        mg["_device_info"] = mg_res["device_info"]
    if mg_res.get("диагностика"):
        # туннель поднялся, а службы нет: кладём в слепок, что телефон предлагает вместо неё
        mg["_диагностика"] = mg_res["диагностика"]
    quality["mobilegestalt_канал"] = mg_res.get("канал")
    quality["время_с"]["mobilegestalt"] = round(time.monotonic() - t, 2)

    log("джейлбрейк…")
    t = time.monotonic()
    jb = await jailbreak.probe(ld)
    quality["время_с"]["джейлбрейк"] = round(time.monotonic() - t, 2)

    log("panic full…")
    t = time.monotonic()
    pan = await panic.probe(ld)
    quality["время_с"]["паника"] = round(time.monotonic() - t, 2)

    log("профили и надзор…")
    t = time.monotonic()
    mdm_info = await mdm.probe(ld)
    quality["время_с"]["mdm"] = round(time.monotonic() - t, 2)

    # NANDInfo: разбор и сверка прошивки с NVMe-контроллером
    disk = domains.get("com.apple.disk_usage") or {}
    nv_fw = txt(deep(nodes.get("nvme") or {}, "Firmware Revision"))
    nand_summary = nand.summarize(disk.get("NANDInfo"), nv_fw) if disk.get("NANDInfo") else {}

    quality["время_с"]["всего"] = round(time.monotonic() - t0, 2)
    return {
        "snapshot_version": SNAPSHOT_VERSION,
        "когда": datetime.now().isoformat(timespec="seconds"),
        "root": root,
        "domains": domains,
        "node_names": sorted(names),
        "nodes": nodes,
        "ioreg_planes": {"IOService": tree, "IODeviceTree": dtree},
        "mobilegestalt": mg,
        "jailbreak": jb,
        "panic": pan,
        "mdm": mdm_info,
        "nand_summary": nand_summary,
        "quality": quality,
    }
