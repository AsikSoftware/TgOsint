# -*- coding: utf-8 -*-
"""Точка входа сервера: uvicorn pintel_server.main:app"""
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from .auth import LoginRequired
from .config import settings
from .db import init_db
from .routers import kiosk_api, web

HERE = os.path.dirname(os.path.abspath(__file__))


def create_app(init_sqlite=True) -> FastAPI:
    @asynccontextmanager
    async def lifespan(_app):
        if init_sqlite and settings.is_sqlite:
            init_db()                    # для разработки; на сервере таблицы создаёт alembic
        yield

    app = FastAPI(title="Pintel Server", docs_url="/api/docs", redoc_url=None, lifespan=lifespan)
    app.mount("/static", StaticFiles(directory=os.path.join(HERE, "static")), name="static")
    app.include_router(kiosk_api.router)
    app.include_router(web.router)

    @app.exception_handler(LoginRequired)
    async def _login_required(request: Request, exc):
        return RedirectResponse("/login", 303)

    @app.get("/healthz")
    def healthz():
        return {"ok": True}

    return app


app = create_app()
