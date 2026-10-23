"""App factory FastAPI. Tidak ada efek samping saat import."""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from webapp.core.logging import configure_logging
from webapp.core.middleware import install_middleware
from webapp.core.settings import PROJECT_ROOT, require_auth_settings
from webapp.routes import auth, builder, home, intel, market, sim, territory
from webapp.routes.error_handlers import register_error_handlers
from webapp.routes.rate_limit import limiter

STATIC_DIR = PROJECT_ROOT / "webapp" / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    require_auth_settings()
    logging.getLogger("webapp").info("Webapp siap")
    yield


def create_app() -> FastAPI:
    app = FastAPI(
        title="Bwabwa",
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.state.limiter = limiter
    install_middleware(app)
    register_error_handlers(app)
    app.include_router(auth.router)
    app.include_router(home.router)
    app.include_router(market.router)
    app.include_router(territory.router)
    app.include_router(intel.router)
    app.include_router(sim.router)
    app.include_router(builder.router)
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    return app
