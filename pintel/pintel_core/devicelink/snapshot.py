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

from . import nand
from .nodes import (CAMERA_FALLBACK, CAMERA_RE, DOMAINS, FIXED_NODES, NVME_FALLBACK,
                    NVME_RE, collect_entry_names, deep, pick_names, txt)

SNAPSHOT_VERSION = 2


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
        for k in ("TotalDataAvailable", "TotalDataCapacity"):
            if first.get(k) != second.get(k):
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

    cam_names = pick_names(names, CAMERA_RE, CAMERA_FALLBACK)
    nvme_names = pick_names(names, NVME_RE, NVME_FALLBACK)

    log("узлы…")
    t = time.monotonic()
    nodes = {}
    for name in FIXED_NODES:
        nodes[name] = await _retry(lambda n=name: diag.ioregistry(name=n), name, quality)
    for key, cands in (("camera", cam_names), ("nvme", nvme_names)):
        nodes[key] = None
        for n in cands:
            v = await _retry(lambda n=n: diag.ioregistry(name=n), n, quality, tries=2)
            if v:
                nodes[key] = v
                quality[f"{key}_узел"] = n
                break
    quality["время_с"]["узлы"] = round(time.monotonic() - t, 2)

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
        "nand_summary": nand_summary,
        "quality": quality,
    }
