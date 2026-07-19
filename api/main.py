"""FastAPI entry point for Podcast Studio API.

Start locally:
    uvicorn api.main:app --reload --port 8000

Or from the project root:
    python -m uvicorn api.main:app --reload --port 8000
"""
from __future__ import annotations

import logging
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# ---------------------------------------------------------------------------
# Ensure src/ is importable before any local imports
# ---------------------------------------------------------------------------
_ROOT = Path(__file__).resolve().parent.parent  # project root
_SRC = _ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Lifespan — load env + build Gemini client once at startup
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Load .env (no-op if file missing or python-dotenv not installed)
    try:
        from dotenv import load_dotenv

        env_path = _ROOT / ".env"
        if env_path.exists():
            load_dotenv(dotenv_path=env_path, override=False)
            log.info(".env loaded from %s", env_path)
        else:
            log.info("No .env file found at %s — relying on process environment", env_path)
    except ImportError:
        log.info("python-dotenv not installed — skipping .env load")

    # Build Gemini client
    from google import genai

    api_key = os.getenv("GEMINI_API_KEY", "").strip() or os.getenv("API_KEY", "").strip()
    use_vertex = os.getenv("GOOGLE_GENAI_USE_VERTEXAI", "").strip().lower() in (
        "1",
        "true",
        "yes",
    )

    if use_vertex:
        project = os.getenv("GOOGLE_CLOUD_PROJECT", "").strip()
        location = os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1").strip() or "us-central1"
        if not project:
            log.error(
                "GOOGLE_GENAI_USE_VERTEXAI is set but GOOGLE_CLOUD_PROJECT is missing"
            )
            raise RuntimeError("GOOGLE_CLOUD_PROJECT env var is required for Vertex AI")
        creds = _build_vertex_credentials()
        client = genai.Client(
            vertexai=True, project=project, location=location, credentials=creds
        )
        # Client thứ hai trỏ global endpoint — bể dynamic shared quota lớn hơn
        # nhiều so với 1 region, dùng cho text + sinh ảnh (Veo vẫn cần region).
        client_global = genai.Client(
            vertexai=True, project=project, location="global", credentials=creds
        )
        log.info(
            "Gemini client initialised via Vertex AI (project=%s, location=%s + global)",
            project, location,
        )
    elif api_key:
        client = genai.Client(api_key=api_key)
        client_global = client
        log.info("Gemini client initialised via API key …%s", api_key[-4:])
    else:
        log.warning(
            "Neither GEMINI_API_KEY nor GOOGLE_GENAI_USE_VERTEXAI is configured. "
            "Requests that call Gemini will fail at runtime. "
            "Set GEMINI_API_KEY or enable GOOGLE_GENAI_USE_VERTEXAI=true with GOOGLE_CLOUD_PROJECT."
        )
        client = None  # type: ignore[assignment]
        client_global = None  # type: ignore[assignment]

    app.state.genai_client = client
    app.state.genai_client_global = client_global
    yield
    log.info("API shutdown")


def _build_vertex_credentials():
    """Build GCP service account credentials for Vertex AI."""
    import json

    from google.oauth2 import service_account

    _SCOPES = ["https://www.googleapis.com/auth/cloud-platform"]

    raw = os.getenv("GCP_SERVICE_ACCOUNT_JSON", "").strip()
    if raw:
        info = json.loads(raw)
        return service_account.Credentials.from_service_account_info(info, scopes=_SCOPES)

    path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "").strip()
    if path:
        resolved = Path(path) if Path(path).is_absolute() else _ROOT / path
        if resolved.exists():
            return service_account.Credentials.from_service_account_file(
                str(resolved), scopes=_SCOPES
            )
        else:
            log.warning("GOOGLE_APPLICATION_CREDENTIALS path not found: %s", resolved)

    return None  # Fallback to ADC (works locally with `gcloud auth application-default login`)




# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Podcast Studio API",
    description="FastAPI backend for the Podcast Studio app",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS — open in dev; restrict CORS_ORIGINS env var in production
_cors_origins_raw = os.getenv("CORS_ORIGINS", "*")
_cors_origins = (
    ["*"]
    if _cors_origins_raw.strip() == "*"
    else [o.strip() for o in _cors_origins_raw.split(",") if o.strip()]
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------

from api.routes.auth_router import router as auth_router
from api.routes.elevenlabs import router as elevenlabs_router
from api.routes.podcast import router as podcast_router
from api.routes.outlines import router as outlines_router
from api.routes.topics import router as topics_router
from api.routes.affiliate import router as affiliate_router

app.include_router(auth_router, prefix="/api/auth", tags=["auth"])
app.include_router(elevenlabs_router, prefix="/api/elevenlabs", tags=["elevenlabs"])
app.include_router(podcast_router, prefix="/api/podcast", tags=["podcast"])
app.include_router(outlines_router, prefix="/api/podcast", tags=["outlines"])
app.include_router(topics_router, prefix="/api/topics", tags=["topics"])
app.include_router(affiliate_router, prefix="/api/affiliate", tags=["affiliate"])


@app.get("/api/health", tags=["health"])
def health() -> dict[str, str]:
    return {"status": "ok"}
