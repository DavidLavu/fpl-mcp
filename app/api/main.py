import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.routes import init_app
from app.services.fpl_client import aclose_client
from app.util.models import HealthResponse


logger = logging.getLogger("fpl-mcp")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting FPL MCP server...")
    try:
        yield
    finally:
        logger.info("Closing FPL HTTP client...")
        await aclose_client()


app = FastAPI(
    title="FPL MCP Server",
    version="0.1.0",
    description=(
        "Fantasy Premier League MCP-compatible server exposing bootstrap, fixtures, and manager tools."
    ),
    lifespan=lifespan,
)


@app.get("/health", response_model=HealthResponse, tags=["health"])
def health() -> HealthResponse:
    return HealthResponse(status="ok")


# Register routers and middleware
init_app(app)
