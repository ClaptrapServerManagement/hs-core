
import asyncio
import contextlib
from contextlib import asynccontextmanager
from fastapi import FastAPI
import logging

from . import __version__, config, db, monitor
from .errors import register_error_handlers
from .routes import components, resources

PREFIX = "/api/v1"

@asynccontextmanager
async def lifespan(app: FastAPI):
    await db.connect()
    monitor_task = asyncio.create_task(monitor.run_monitor())
    yield
    monitor_task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await monitor_task
    await db.close()

app = FastAPI(
    title="Homeserver Manager API",
    version=__version__,
    lifespan=lifespan,
    docs_url=f"{PREFIX}/docs",
    openapi_url=f"{PREFIX}/openapi.json",
    redoc_url=None,
)
register_error_handlers(app)
app.include_router(components.router, prefix=PREFIX)
app.include_router(resources.router, prefix=PREFIX)

def run() -> None:
    import uvicorn

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    uvicorn.run(app, host=config.API_HOST, port=config.API_PORT)

if __name__ == "__main__":
    run()