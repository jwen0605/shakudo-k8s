import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from api.k8s.client import init_k8s
from api.routes.deployments import router as deployments_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_k8s()
    yield


app = FastAPI(
    title="Shakudo K8s Manager",
    description="Kubernetes Workload Deployment & Monitoring Platform",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(deployments_router)

# Serve the web UI from /ui
_UI_DIR = os.path.join(os.path.dirname(__file__), "..", "ui")


@app.get("/", include_in_schema=False)
def serve_ui():
    index = os.path.join(_UI_DIR, "index.html")
    return FileResponse(index)


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    return JSONResponse(
        status_code=500,
        content={"error": "Internal server error", "detail": str(exc)},
    )
