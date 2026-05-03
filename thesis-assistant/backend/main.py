# backend/main.py
"""
FastAPI application — single entry point.

Start with:   python main.py          (from backend/ folder)
Or:           uvicorn main:app --reload --port 8001
API docs:     http://127.0.0.1:8001/docs
"""
import asyncio
import sys
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

import logging
from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import FastAPI, UploadFile, File, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse, Response

from config import check_env, LOG_DIR
from database import init_db
from models import QueryRequest, QueryResponse, TranscribeResponse, SynthesizeRequest
from scrapers import get_concerts, get_route, search_routes_by_stop, get_available_routes
from scrapers.ttc_data import populate_cache_from_csv
from nlp import parse_intent, build_response
from voice.stt import transcribe
from voice.tts import synthesize


# ── Logging ───────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(LOG_DIR / "app.log", encoding="utf-8"),
    ],
)
log = logging.getLogger("main")


# ── Startup ───────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    missing = check_env()
    if missing:
        log.warning("Missing env vars: %s", missing)

    init_db()
    routes = populate_cache_from_csv()
    log.info("TTC cache ready: %d routes loaded", len(routes))

    # Warm concert cache in background — server starts instantly,
    # TKT data fills in ~15 seconds behind the scenes
    from scrapers.tkt_scraper import warm_concert_cache
    warm_concert_cache()

    yield


# ── App ───────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="თბილისის ხელმისაწვდომი ასისტენტი",
    description=(
        "ქართული ხმოვანი ასისტენტი — კონცერტები და ავტობუსები.\n\n"
        "Georgian voice assistant for concerts (TKT.ge) and buses (TTC)."
    ),
    version="1.0.0",
    lifespan=lifespan,
)
from fastapi.staticfiles import StaticFiles
app.mount("/app", StaticFiles(directory="../frontend", html=True), name="frontend")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],   # tighten for production
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Root — redirect to docs instead of 404 ───────────────────────────────────

@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse("/app")


# ── Health ────────────────────────────────────────────────────────────────────

@app.get("/health", tags=["meta"])
def health():
    """
    Standard health-check.  Confirms the API is running and lists
    which bus routes are loaded in the cache.
    (This is NOT the same as /buses — /buses is the data endpoint,
    /health just tells you the server is alive.)
    """
    return {
        "status": "ok",
        "time": datetime.now().isoformat(),
        "routes_cached": get_available_routes(),
    }


# ── Concerts ──────────────────────────────────────────────────────────────────

@app.get("/concerts", tags=["concerts"])
async def concerts_endpoint(
    days: int = Query(default=3, ge=1, le=30, description="Days ahead to search"),
):
    """Return upcoming concerts from TKT.ge (cached every 3 hours)."""
    try:
        return await get_concerts(days_ahead=days)
    except Exception as e:
        log.error("Concert scrape failed: %s", e)
        raise HTTPException(
            status_code=503,
            detail="TKT.ge-დან ინფორმაციის წამოღება ვერ მოხერხდა. სცადეთ მოგვიანებით.",
        )


# ── Buses ─────────────────────────────────────────────────────────────────────

@app.get("/buses", tags=["buses"])
def available_routes():
    """List all bus route numbers that have data."""
    return {"routes": get_available_routes()}


@app.get("/buses/{route_number}", tags=["buses"])
def bus_route(route_number: str):
    """Full stop list and timetable for one route."""
    route = get_route(route_number)
    if not route:
        available = get_available_routes()
        raise HTTPException(
            status_code=404,
            detail=f"{route_number}-ე მარშრუტი ვერ მოიძებნა. ხელმისაწვდომია: {', '.join(available)}",
        )
    return route


@app.get("/buses/search/stop", tags=["buses"])
def search_stop(q: str = Query(..., description="Stop name — partial Georgian is fine")):
    """Find which routes serve a stop whose name contains `q`."""
    results = search_routes_by_stop(q)
    if not results:
        raise HTTPException(
            status_code=404,
            detail=f"'{q}' — ამ სახელით გაჩერება ვერ მოიძებნა.",
        )
    return results


# ── Journey planning — "how do I get to X?" ──────────────────────────────────

@app.get("/journey", tags=["journey"])
def journey_to(
    q: str = Query(..., description="Place or stop name in Georgian"),
):
    """
    Find which bus routes serve a given place.
    Example: /journey?q=ფილარმონია
    Returns the routes and the exact stop names, plus a ready-to-speak Georgian sentence.
    """
    results = search_routes_by_stop(q)
    if not results:
        raise HTTPException(
            status_code=404,
            detail=f"'{q}' — ამ ადგილთან ახლოს ავტობუსის გაჩერება ვერ მოიძებნა.",
        )

    # Group: route_number → [stop_name, ...]
    routes_map: dict[str, list[str]] = {}
    for r in results:
        routes_map.setdefault(r["route_number"], []).append(r["stop_name"])

    route_sentence_parts = [
        f"{rn}-ე მარშრუტი (გაჩერება: {stops[0]})"
        for rn, stops in routes_map.items()
    ]

    georgian_response = (
        f"'{q}'-ში მისასვლელად შეგიძლიათ ისარგებლოთ შემდეგი მარშრუტებით: "
        + ", ".join(route_sentence_parts)
        + "."
    )

    return {
        "place_query": q,
        "route_numbers": list(routes_map.keys()),
        "stops": results,
        "response_georgian": georgian_response,
    }


# ── Main query pipeline (text → intent → data → Georgian response) ────────────

@app.post("/query", response_model=QueryResponse, tags=["query"])
async def query_endpoint(body: QueryRequest):
    """
    Full pipeline: Georgian text → intent → data → Georgian response text.
    The frontend calls this after transcription.
    """
    intent = parse_intent(body.text)
    log.info("Intent: %-20s | Input: %r", intent.intent, body.text)

    results = []
    venue_bus_offer = None   # optional follow-up offer for concerts

    if intent.intent == "concert_search":
        results = await get_concerts(days_ahead=intent.days or 30)

        if intent.specific_date:
            date_filter = intent.specific_date.lower()
            results = [c for c in results if date_filter in c.get("date", "").lower()]

        if intent.venue:
            venue_words = intent.venue.lower().split()
            results = [c for c in results
                       if any(word in c.get("venue", "").lower()
                              for word in venue_words if len(word) > 2)
                       or any(word in c.get("name", "").lower()
                              for word in venue_words if len(word) > 2)]

        # Only offer bus directions to venues that are IN the filtered results
        venues = list({c["venue"] for c in results[:5]
                       if c.get("venue") and c["venue"] != "N/A"})
        if venues:
            venue_bus_offer = venues[0]



    elif intent.intent == "bus_search":

        if intent.route:

            route = get_route(intent.route)

            if route and intent.place:

                place_lower = intent.place.lower()

                matching = [s for s in route["stops"] if place_lower in s["name"].lower()]

                results = matching[:5] if matching else route["stops"][:5]

            else:

                results = route["stops"][:5] if route else []


        elif intent.place:

            # No route number but has a place — treat as journey search

            intent.intent = "journey_search"

            search_term = intent.place.split()[0]

            raw_results = search_routes_by_stop(search_term)

            # Enrich with schedule data

            enriched = []

            for r in raw_results[:5]:

                route = get_route(r["route_number"])

                if route:

                    for stop in route["stops"]:

                        if stop["index"] == r["stop_index"]:
                            enriched.append({**r, "schedule": stop["schedule"]})

                            break

                    else:

                        enriched.append(r)

                else:

                    enriched.append(r)

            results = enriched

        else:

            results = []




    elif intent.intent == "journey_search":

        if intent.place:

            search_term = intent.place.split()[0]

            raw_results = search_routes_by_stop(search_term)

            enriched = []

            for r in raw_results[:5]:

                route = get_route(r["route_number"])

                if route:

                    for stop in route["stops"]:

                        if stop["index"] == r["stop_index"]:
                            enriched.append({**r, "schedule": stop["schedule"]})

                            break

                    else:

                        enriched.append(r)

                else:

                    enriched.append(r)

            results = enriched
    response_text = build_response(intent, results, venue_bus_offer=venue_bus_offer)
    print(f">>> RESPONSE: {repr(response_text[:100])}", flush=True)  # ADD THIS

    return QueryResponse(
        intent=intent.intent,
        response_text=response_text,
        results=[dict(r) if hasattr(r, "__dict__") else r for r in results[:5]],
        venue_bus_offer=venue_bus_offer,
    )


# ── Voice: transcribe ─────────────────────────────────────────────────────────

@app.post("/transcribe", response_model=TranscribeResponse, tags=["voice"])
async def transcribe_endpoint(
    audio: UploadFile = File(...),
    engine: str = Query(default="google", pattern="^(whisper|google)$"),
):
    """
    Transcribe uploaded audio to Georgian text.
    engine: whisper (local, default) | google (Cloud STT API)
    """
    audio_bytes = await audio.read()
    try:
        return transcribe(audio_bytes, engine=engine)
    except Exception as e:
        log.error("STT failed (%s): %s", engine, e)
        raise HTTPException(
            status_code=500,
            detail=f"ხმის ამოცნობა ვერ მოხერხდა ({engine}): {e}",
        )


@app.get("/debug/tts", tags=["meta"])
async def debug_tts():
    import asyncio, concurrent.futures, traceback

    def _run_in_thread():
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            import io, edge_tts
            async def _go():
                buf = io.BytesIO()
                async for chunk in edge_tts.Communicate("გამარჯობა", "ka-GE-EkaNeural").stream():
                    if chunk["type"] == "audio":
                        buf.write(chunk["data"])
                return buf.getvalue()

            return loop.run_until_complete(_go())
        except Exception as e:
            return traceback.format_exc()
        finally:
            loop.close()

    loop = asyncio.get_event_loop()
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        result = await loop.run_in_executor(pool, _run_in_thread)

    if isinstance(result, bytes):
        return {"bytes": len(result), "ok": True}
    return {"error": result, "ok": False}


@app.get("/debug/tts2", tags=["meta"])
async def debug_tts2():
    import asyncio, concurrent.futures, io

    text = "გამარჯობა, მე ვარ თბილისის ასისტენტი"

    def _run_in_thread():
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            import edge_tts
            async def _go():
                buf = io.BytesIO()
                async for chunk in edge_tts.Communicate(text, "ka-GE-EkaNeural").stream():
                    if chunk["type"] == "audio":
                        buf.write(chunk["data"])
                return buf.getvalue()
            return loop.run_until_complete(_go())
        finally:
            loop.close()

    loop = asyncio.get_event_loop()
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        audio = await loop.run_in_executor(pool, _run_in_thread)

    return Response(content=audio, media_type="audio/mpeg")


# ── Voice: synthesize — body not query param (Georgian text is long) ──────────

@app.post("/synthesize", tags=["voice"])
async def synthesize_endpoint(body: SynthesizeRequest):
    try:
        import asyncio, concurrent.futures, io

        text = str(body.text)  # extract to plain string BEFORE the thread
        print(f">>> SYNTHESIZE CALLED: {repr(text)}", flush=True)

        def _run_in_thread():
            asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                import edge_tts
                async def _go():
                    buf = io.BytesIO()
                    async for chunk in edge_tts.Communicate(text, "ka-GE-EkaNeural").stream():
                        if chunk["type"] == "audio":
                            buf.write(chunk["data"])
                    return buf.getvalue()
                return loop.run_until_complete(_go())
            finally:
                loop.close()

        loop = asyncio.get_event_loop()
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            audio = await loop.run_in_executor(pool, _run_in_thread)

        if not audio:
            raise RuntimeError("No audio returned.")
        return Response(
            content=audio,
            media_type="audio/mpeg",
            headers={
                "Content-Length": str(len(audio)),
                "Accept-Ranges": "bytes",
                "Cache-Control": "no-cache",
            }
        )
    except Exception as e:
        log.error("TTS failed: %s", e)
        raise HTTPException(status_code=500, detail=f"მეტყველების სინთეზი ვერ მოხერხდა: {e}")


@app.get("/debug/filter", tags=["meta"])
async def debug_filter():
    from database import load_concerts
    from scrapers.tkt_scraper import _filter_by_days
    from datetime import datetime

    cached, _ = load_concerts()
    now = datetime.now()

    filtered_2 = _filter_by_days(cached or [], 2)
    filtered_30 = _filter_by_days(cached or [], 30)

    return {
        "server_time": now.isoformat(),
        "total_cached": len(cached or []),
        "days_2_count": len(filtered_2),
        "days_30_count": len(filtered_30),
        "days_2_dates": list({c["date"] for c in filtered_2}),
        "first_cached_date": (cached or [{}])[0].get("date"),
        "last_cached_date": (cached or [{}])[-1].get("date"),
    }


@app.get("/debug/voices", tags=["meta"])
def debug_voices():
    from google.cloud import texttospeech
    client = texttospeech.TextToSpeechClient()
    voices = client.list_voices(language_code="ka")
    return {"voices": [v.name for v in voices.voices]}

# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="127.0.0.1", port=8001, reload=True)