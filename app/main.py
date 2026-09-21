"""FastAPI application (Step 1: foundation).
from app.retrieval import BM25Retriever
Implemented now:
  GET  /health            200 {"status": "ok"} only when every component is ready
  POST /v1/troubleshoot   validates the request, then returns 501 (pipeline comes later)

Run:  uvicorn app.main:app --reload
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Optional
from app.cache import FastPathCache
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from app.api_models import TroubleshootRequest
from app.articles import ArticleError, load_siis_records
from app.catalog import CatalogError, CatalogIndex
from app.config import Settings
from app.retrieval import BM25Retriever
from app.llm.factory import build_query_provider
from app.llm.solution_factory import build_solution_provider
from app.troubleshoot_service import TroubleshootService
log = logging.getLogger("tapfix")


def create_app(settings: Optional[Settings] = None) -> FastAPI:
    settings = settings or Settings.from_env()
    logging.basicConfig(level=settings.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # Components register here. Later steps add: cache, embeddings, llm.
        app.state.settings = settings
        app.state.ready = {
            "catalog": False,
            "articles": False,
            "retriever": False,
            "pipeline": False,
        }

        # The query provider is initialized when the LLM pipeline is added.
    
        app.state.query_provider = build_query_provider(settings)
        app.state.solution_provider = None
        app.state.troubleshoot_service = None
        app.state.catalog = None
        app.state.siis_records = []
        log.info("starting with settings: %s", settings.safe_dict())  # key is masked

        try:
            app.state.catalog = CatalogIndex.from_file(settings.deeplinks_path)
            app.state.retriever = BM25Retriever(app.state.catalog.real_entries)
            app.state.ready["catalog"] = True
            app.state.ready["retriever"] = True

            log.info(
                "catalog loaded: %d entries; BM25 retriever ready: %d entries",
                len(app.state.catalog),
                len(app.state.retriever),
            )
        except CatalogError as exc:
            log.error("catalog failed to load: %s", exc)

        try:
            app.state.siis_records = load_siis_records(settings.siis_path)
            app.state.ready["articles"] = True
            log.info("SIIS articles loaded: %d", len(app.state.siis_records))
        except ArticleError as exc:
            log.error("SIIS articles failed to load: %s", exc)
        if app.state.ready["catalog"] and app.state.ready["retriever"]:
            try:
                app.state.solution_provider = build_solution_provider(settings)

                app.state.cache = FastPathCache(max_entries=10_000)

                app.state.troubleshoot_service = TroubleshootService(
                    retriever=app.state.retriever,
                    catalog=app.state.catalog,
                    query_provider=app.state.query_provider,
                    solution_provider=app.state.solution_provider,
                    cache=app.state.cache,
                )

                app.state.ready["pipeline"] = True

                log.info("troubleshooting pipeline ready")

            except Exception as exc:
                app.state.ready["pipeline"] = False
                log.error(
                    "troubleshooting pipeline failed to initialize: %s",
                    exc,
                )
        else:
            app.state.ready["pipeline"] = False
        yield

    app = FastAPI(
        title="TapFix - Smart Guided Troubleshooting Engine",
        version="0.1.0",
        lifespan=lifespan,
    )

    @app.get("/health")
    def health(request: Request):
        ready = getattr(request.app.state, "ready", None)
        if ready is None:
            return JSONResponse(status_code=503, content={"status": "starting"})
        not_ready = [name for name, ok in ready.items() if not ok]
        if not_ready:
            return JSONResponse(
                status_code=503, content={"status": "unavailable", "not_ready": not_ready}
            )
        return {"status": "ok"}  # exactly the body Samsung specifies

    @app.post("/v1/troubleshoot")
    def troubleshoot(body: TroubleshootRequest, request: Request):
        service = getattr(
            request.app.state,
            "troubleshoot_service",
            None,
        )

        if service is None:
            raise HTTPException(
                status_code=503,
                detail="Troubleshooting pipeline is unavailable.",
            )

        try:
            result = service.troubleshoot(
    query=body.query,
    siis_response=body.siis_response,
)
        except Exception as exc:
            log.exception("troubleshooting request failed")
            raise HTTPException(
                status_code=500,
                detail="Troubleshooting pipeline failed.",
            ) from exc

        return result.response
    @app.get("/v1/cache/stats")
    def cache_stats(request: Request):
        cache = getattr(request.app.state, "cache", None)

        if cache is None:
            raise HTTPException(
                status_code=503,
                detail="Cache is unavailable.",
            )

        return cache.stats()

    return app


app = create_app()