# -*- coding: utf-8 -*-
"""Журнал действий: всё, что делали люди и киоски, хранится всегда."""
from .models import AuditLog


def log(db, actor, action, text, entity=None, entity_id=None, details=None, point_id=None, kiosk=None):
    """actor — User, Kiosk или None (сервер)."""
    if kiosk is not None:
        atype, aid, aname = "kiosk", kiosk.id, f"Киоск {kiosk.name}"
        point_id = point_id or kiosk.point_id
    elif actor is not None:
        atype, aid, aname = "user", actor.id, actor.name
        point_id = point_id or actor.point_id
    else:
        atype, aid, aname = "server", None, "Сервер"
    db.add(AuditLog(actor_type=atype, actor_id=aid, actor_name=aname, action=action, entity=entity,
                    entity_id=entity_id, point_id=point_id, text=text, details=details))
