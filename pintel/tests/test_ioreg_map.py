# -*- coding: utf-8 -*-
"""Карта узлов IORegistry: план приходит деревом {"children": [...]}, имена — в полях узлов."""
import json, os
from pintel_core.devicelink.nodes import (CAMERA_FALLBACK, CAMERA_RE, NVME_FALLBACK, NVME_RE,
                                          OPTIONAL_NODES, collect_entry_names, pick_names)
from pintel_core.devicelink import jailbreak, snapshot
from pintel_core.analysis import report as report_mod

HERE = os.path.dirname(os.path.abspath(__file__))

TREE = {"children": [
    {"IORegistryEntryName": "Root", "IOClass": "IOPlatformExpertDevice", "children": [
        {"IORegistryEntryName": "arm-io", "children": [
            {"IORegistryEntryName": "AppleH13CamIn", "IOClass": "AppleH13CamIn", "SomeProp": 1},
            {"name": "AppleANS3NVMeController", "children": []},
            {"IORegistryEntryName": "AppleBCMWLANCore"},
            {"IORegistryEntryName": "AppleTriStarBuiltIn", "properties": {"x": {"y": 1}}},
        ]},
    ]},
]}


def test_names_from_children_tree():
    names = collect_entry_names(TREE)
    assert {"Root", "arm-io", "AppleH13CamIn", "AppleANS3NVMeController",
            "AppleBCMWLANCore", "AppleTriStarBuiltIn"} <= names
    assert "children" not in names and "properties" not in names
    assert pick_names(names, CAMERA_RE, CAMERA_FALLBACK) == ["AppleH13CamIn"]
    assert pick_names(names, NVME_RE, NVME_FALLBACK) == ["AppleANS3NVMeController"]
    assert pick_names(names, *OPTIONAL_NODES["wifi"]) == ["AppleBCMWLANCore"]
    assert pick_names(names, *OPTIONAL_NODES["port"]) == ["AppleTriStarBuiltIn"]


def test_names_from_dict_keyed_tree_still_work():
    names = collect_entry_names({"AppleSmartBattery": {"CycleCount": 5}, "AppleH10CamIn": {"a": {}}})
    assert {"AppleSmartBattery", "AppleH10CamIn"} <= names


def test_fallback_when_map_empty():
    assert pick_names(set(), CAMERA_RE, CAMERA_FALLBACK) == list(CAMERA_FALLBACK)
    assert pick_names(set(), *OPTIONAL_NODES["touchid"]) == ["AppleMesa"]


def test_jailbreak_verdict_texts():
    assert jailbreak.verdict(None) == "не проверялся"
    assert jailbreak.verdict({"проверено": False, "ошибка": "нет AFC"}) == "не проверялся (нет AFC)"
    assert jailbreak.verdict({"проверено": True, "признаки": []}) == "следов нет"
    assert jailbreak.verdict({"проверено": True, "признаки": ["/var/jb"]}).startswith("НАЙДЕНЫ СЛЕДЫ: /var/jb")


def _real():
    p = os.path.join(HERE, "fixtures_real", "iphone12_FFXH33T20F0N.snapshot.json")
    return snapshot.loads(open(p, encoding="utf-8").read())


def test_report_jailbreak_and_colour_code():
    snap = _real()
    snap["jailbreak"] = {"проверено": True, "признаки": ["/var/lib/dpkg/status"], "ошибки": {}}
    snap["mobilegestalt"] = {"DeviceEnclosureColor": 9, "DeviceColor": 1}
    rep = report_mod.build(snap)
    assert any("джейлбрейк" in x for x in rep["внимание"])
    assert rep["паспорт"]["код_цвета_корпуса"] == 9 and rep["паспорт"]["цвет"] == "синий"
    assert rep["джейлбрейк"].startswith("НАЙДЕНЫ") and rep["mobilegestalt"] == "есть"

    snap["mobilegestalt"] = {"недоступен": "DeprecationError: iOS 17.4+"}
    snap["jailbreak"] = {"проверено": False, "признаки": [], "ошибка": "timeout"}
    rep = report_mod.build(snap)
    assert rep["паспорт"]["код_цвета_корпуса"] is None and rep["mobilegestalt"] == "недоступен"
    assert rep["джейлбрейк"].startswith("не проверялся")
    assert not any("джейлбрейк" in x for x in rep["внимание"])
