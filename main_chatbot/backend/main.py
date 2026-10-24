from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from starlette.concurrency import run_in_threadpool

from .config import Settings
from .middleware import RequestContextMiddleware
from .pandasai_service import PandasAIService
from .schemas import ChatRequest, ChatResponse, DatasetResponse, HealthResponse
from .session_store import SessionStore

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    settings = Settings.from_environment()
    sessions = SessionStore(
        ttl_minutes=settings.session_ttl_minutes,
        max_sessions=settings.max_active_sessions,
    )
    service = PandasAIService(settings, sessions)

    app = FastAPI(
        title="Business Analytics Chatbot API",
        version="1.0.0",
        description="Chat with CSV and Excel business datasets using PandasAI.",
    )
    app.add_middleware(RequestContextMiddleware)
    app.state.settings = settings
    app.state.sessions = sessions
    app.state.service = service

    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.cors_origins),
        allow_credentials=False,
        allow_methods=["GET", "POST", "DELETE"],
        allow_headers=["*"],
    )

    @app.get("/health", response_model=HealthResponse)
    async def health() -> HealthResponse:
        return HealthResponse(status="ok", llm_configured=bool(settings.groq_api_key))

    @app.post("/datasets", response_model=DatasetResponse, status_code=status.HTTP_201_CREATED)
    async def upload_dataset(file: UploadFile = File(...)) -> DatasetResponse:
        try:
            content = await file.read(settings.max_upload_size_bytes + 1)
            return await run_in_threadpool(
                service.create_dataset, file.filename or "dataset.csv", content
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            logger.exception("Dataset upload failed")
            raise HTTPException(status_code=500, detail="Dataset upload failed.") from exc

    @app.post("/sessions/{session_id}/chat", response_model=ChatResponse)
    async def chat(session_id: str, request: ChatRequest) -> ChatResponse:
        try:
            return await run_in_threadpool(service.chat, session_id, request.question)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except Exception as exc:
            logger.exception("Chat request failed for session %s", session_id)
            error_text = str(exc)
            if "ratelimit" in error_text.lower() or "rate limit" in error_text.lower() or "429" in error_text:
                detail = "The AI rate limit was reached. Please retry in a few seconds."
            else:
                detail = "The analysis request failed. Check the backend log for details."
            raise HTTPException(status_code=502, detail=detail) from exc

    @app.get("/sessions/{session_id}/dashboard")
    async def dashboard(session_id: str) -> dict:
        try:
            return await run_in_threadpool(service.build_dashboard, session_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            logger.exception("Dashboard generation failed for session %s", session_id)
            raise HTTPException(status_code=500, detail="The dashboard could not be generated.") from exc

    @app.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
    async def delete_session(session_id: str) -> None:
        try:
            await run_in_threadpool(service.delete_dataset, session_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/files/charts/{filename}")
    async def get_chart(filename: str) -> FileResponse:
        chart_path = settings.chart_directory / Path(filename).name
        if not chart_path.is_file():
            raise HTTPException(status_code=404, detail="Chart not found.")
        return FileResponse(chart_path, media_type="image/png", filename=chart_path.name)

    return app


app = create_app()

