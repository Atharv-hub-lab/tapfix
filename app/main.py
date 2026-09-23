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
import re
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

def _retrieve_siis_for_query(query: str, records):
    """
    Find a relevant local SIIS article when the caller does not
    provide a siis_response.

    Retrieval is intentionally conservative: an article must share
    at least two meaningful query terms and at least one of those
    terms must appear in the article title or original scenario.
    """
    if not query or not records:
        return None

    aliases = {
        "display": "screen",
        "displays": "screen",
        "dark": "black",
        "blank": "black",
        "nothing": "black",
        "visible": "black",
        "smartphone": "phone",
        "smartphones": "phone",
    }

    stopwords = {
        "my",
        "the",
        "a",
        "an",
        "is",
        "are",
        "was",
        "were",
        "and",
        "or",
        "to",
        "on",
        "in",
        "of",
        "for",
        "with",
        "i",
        "it",
        "this",
        "that",
        "properly",
        "very",
        "really",
        "just",
        "can",
        "cannot",
        "not",
    }

    def words(text: str) -> set[str]:
        tokens = re.findall(r"[a-z0-9]+", text.lower())

        result = set()

        for token in tokens:
            if token in stopwords:
                continue

            token = aliases.get(token, token)

            if len(token) >= 4:
                result.add(token)

        return result

    # Handle the common vague complaint:
    # "I can't see anything on the screen" -> black + screen.
    normalized_query = re.sub(
        r"\bcan'?t\s+see\s+anything\b",
        "black screen",
        query.lower(),
    )

    query_words = words(normalized_query)

    if not query_words:
        return None

    best_record = None
    best_score = 0.0

    for record in records:
        record_text = " ".join(
            [
                record.original_query,
                record.title,
                record.content[:2500],
            ]
        )

        record_words = words(record_text)

        overlap = query_words & record_words

        # One shared word is not enough to select an SIIS article.
        if len(overlap) < 2:
            continue

        title_words = words(record.title)
        original_words = words(record.original_query)

        title_overlap = query_words & title_words
        original_overlap = query_words & original_words

        # Require at least one strong match from the title or
        # original scenario, not only from arbitrary article content.
        if not title_overlap and not original_overlap:
            continue

        score = (
            len(overlap)
            + (2.0 * len(title_overlap))
            + (1.5 * len(original_overlap))
        )

        if score > best_score:
            best_score = score
            best_record = record

    if best_record is None:
        return None

    print(
        f"[INFO] Auto SIIS retrieval selected: "
        f"{best_record.id} - {best_record.title}"
    )

    return {
        "title": best_record.title,
        "content": best_record.content,
    }

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
            effective_siis_response = body.siis_response

            if (
                effective_siis_response is None
                or (
                    isinstance(effective_siis_response, str)
                    and not effective_siis_response.strip()
                )
            ):
                effective_siis_response = _retrieve_siis_for_query(
                    body.query,
                    request.app.state.siis_records,
                )

            result = service.troubleshoot(
                query=body.query,
                siis_response=effective_siis_response,
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