import asyncio
import secrets
from collections import Counter
from contextlib import asynccontextmanager, suppress
from pathlib import Path

from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from fastapi import FastAPI

from app import auth, branding, game_config, server, socket, users
from app.adapters.mock import MockAdapter, UnconfiguredAdapter
from app.adapters.screen import ScreenAdapter
from app.adapters.tmux import TmuxAdapter
from app.config import Settings, load_profile, load_settings
from app.db import database
from app.errors import install_errors
from app.http import RequestLimits
from app.monitor import Monitor

API = "/api/v1"


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or load_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        config = settings
        state = app.state
        profile = load_profile(config)
        state.profile = profile
        if profile is None:
            state.adapter = MockAdapter() if config.env == "development" else UnconfiguredAdapter()
        else:
            state.adapter = (
                TmuxAdapter(profile) if profile.adapter == "tmux" else ScreenAdapter(profile)
            )
        state.control, state.upload = asyncio.Lock(), asyncio.Lock()
        state.site_upload = asyncio.Lock()
        state.limiter = auth.LoginLimit()
        state.password_limiter = auth.LoginLimit()
        state.socket_limiter = auth.LoginLimit(ip_limit=30, user_limit=120)
        state.dummy_hash = auth.hash_password("", secrets.token_urlsafe(32))
        state.tickets = {}
        state.sockets = Counter()
        engine = database(config.db_path)
        state.engine = engine
        try:
            alembic = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
            head = ScriptDirectory.from_config(alembic).get_current_head()
            with engine.connect() as conn:
                if MigrationContext.configure(conn).get_current_revision() != head:
                    raise RuntimeError("Run alembic upgrade head before starting the panel")
            state.monitor = Monitor()
            monitor_task = asyncio.create_task(state.monitor.run(state.adapter))
            try:
                yield
            finally:
                monitor_task.cancel()
                with suppress(asyncio.CancelledError):
                    await monitor_task
        finally:
            engine.dispose()

    app = FastAPI(
        title="Minecraft Panel",
        docs_url=None if settings.env == "production" else "/docs",
        redoc_url=None,
        openapi_url=None if settings.env == "production" else "/openapi.json",
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.add_middleware(RequestLimits, settings=settings)
    install_errors(app)
    for router in (
        auth.router,
        users.router,
        branding.router,
        server.router,
        game_config.router,
        socket.api,
    ):
        app.include_router(router, prefix=API)
    app.include_router(socket.sockets)

    @app.get("/healthz")
    async def health() -> dict[str, bool]:
        return {"ok": True}

    return app


app = create_app()
