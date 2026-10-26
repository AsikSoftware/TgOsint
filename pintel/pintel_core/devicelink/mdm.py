# -*- coding: utf-8 -*-
"""Корпоративный надзор (MDM/DEP) — через службу профилей com.apple.mobile.MCInstall.

Работает одинаково на всех iPhone и версиях iOS (то, что смотрят Apple Configurator
и 3uTools), в отличие от узла AIDBus, которого нет у аппаратов с USB‑C.
  CloudConfiguration — привязка к организации через DEP: IsSupervised, IsMandatory,
                       IsMDMUnremovable, OrganizationName, ConfigurationURL
  ProfileList        — установленные профили; MDM-профиль даёт организации власть над телефоном
"""
import asyncio


def _bool(v):
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return bool(v)
    if isinstance(v, str):
        return v.strip().lower() in ("1", "true", "yes")
    return False


async def probe(ld, timeout=12):
    """→ {прочитано, cloud: {...}|None, профили: [{id, имя, организация, активен}], ошибка}."""
    try:
        from pymobiledevice3.services.mobile_config import MobileConfigService
    except Exception as e:                                   # noqa: BLE001
        return {"прочитано": False, "ошибка": f"нет службы профилей: {e}"}

    async def run():
        out = {"прочитано": True, "cloud": None, "профили": [], "ошибка": None}
        async with MobileConfigService(ld) as mc:
            try:
                out["cloud"] = await mc.get_cloud_configuration() or {}
            except Exception as e:                           # noqa: BLE001
                out["ошибка"] = f"cloud: {type(e).__name__}: {str(e)[:120]}"
            try:
                pl = await mc.get_profile_list() or {}
                meta = pl.get("ProfileMetadata") or {}
                manifest = pl.get("ProfileManifest") or {}
                for pid in list(meta.keys()) or list(manifest.keys()):
                    m = meta.get(pid) or {}
                    out["профили"].append({
                        "id": str(pid)[:200], "имя": str(m.get("PayloadDisplayName") or "")[:200],
                        "организация": str(m.get("PayloadOrganization") or "")[:200],
                        "описание": str(m.get("PayloadDescription") or "")[:300],
                        "активен": _bool((manifest.get(pid) or {}).get("IsActive", True)),
                    })
            except Exception as e:                           # noqa: BLE001
                out["ошибка"] = (out["ошибка"] or "") + f" profiles: {type(e).__name__}: {str(e)[:120]}"
        return out

    try:
        return await asyncio.wait_for(run(), timeout)
    except Exception as e:                                   # noqa: BLE001
        return {"прочитано": False, "ошибка": f"{type(e).__name__}: {str(e)[:160]}"}


MDM_HINTS = ("mdm", "device management", "управлен", "enroll", "supervis")


def verdict(m):
    """→ (True/False/None, почему). None — служба не ответила."""
    if not m or not m.get("прочитано"):
        return None, (m or {}).get("ошибка") or "служба профилей не ответила"
    cc = m.get("cloud") or {}
    org = cc.get("OrganizationName") or ""
    if _bool(cc.get("IsSupervised")):
        return True, f"телефон под надзором организации{(' «' + org + '»') if org else ''}"
    if _bool(cc.get("IsMDMUnremovable")) or _bool(cc.get("IsMandatory")) or cc.get("ConfigurationURL"):
        return True, f"телефон привязан к организации через DEP{(' «' + org + '»') if org else ''}"
    for p in m.get("профили") or []:
        text = " ".join(str(p.get(k) or "") for k in ("id", "имя", "описание")).lower()
        if p.get("активен", True) and any(h in text for h in MDM_HINTS):
            return True, f"установлен профиль управления «{p.get('имя') or p.get('id')}»"
    if m.get("профили"):
        return False, "профили есть, но не управляющие: " + ", ".join((p.get("имя") or p.get("id"))[:40] for p in m["профили"][:3])
    return False, "надзора и профилей управления нет"
