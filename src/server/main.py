"""FastAPI server for Zepp PC management."""
import logging
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from src.server.api.devices import router as device_router

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def get_static_dir() -> Path:
    """Get static files directory, works for both dev and PyInstaller."""
    if getattr(sys, "frozen", False):
        # PyInstaller bundle: files are in _MEIPASS
        return Path(sys._MEIPASS) / "src" / "server" / "static"
    return Path(__file__).parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Zepp PC Manager starting...")
    from src.server.api.devices import _devices, _load_config
    from src.ble.client import HuamiDevice
    config = _load_config()
    for mac, info in config.items():
        if mac not in _devices:
            _devices[mac] = HuamiDevice(mac=mac, auth_key=info.get("auth_key"))
    logger.info(f"Restored {len(config)} device(s) from config")
    yield
    logger.info("Shutting down...")


app = FastAPI(
    title="Zepp PC Manager",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(device_router, prefix="/api")

STATIC_DIR = get_static_dir()
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
