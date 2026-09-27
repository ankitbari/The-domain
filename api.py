"""AI Product Hunter Automation - FastAPI backend.

Local automation API for dropshipping product discovery, safety/quality
screening, and supplier-aware ranking. Phase 4: concurrent Decodo scraping
of all ten discovery sources with per-source failure isolation.
"""

import json
import os
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import quote_plus

import requests
import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

load_dotenv()

BACKEND_PORT = 8000

DECODO_API_URL = os.getenv("DECODO_API_URL") or "https://scraper-api.decodo.com/v2/scrape"
DECODO_AUTH_TOKEN = os.getenv("DECODO_AUTH_TOKEN")
DECODO_REQUEST_TIMEOUT = int(os.getenv("DECODO_REQUEST_TIMEOUT") or "120")
DECODO_MAX_WORKERS = int(os.getenv("DECODO_MAX_WORKERS") or "5")

if not DECODO_AUTH_TOKEN:
    raise ValueError("Missing DECODO_AUTH_TOKEN in .env")

# Decodo HTTP client. Defaults to the real requests module; tests monkeypatch
# this attribute so no live Decodo call is ever made from the test suite.
http = requests

app = FastAPI(title="AI Product Hunter Automation API")

# Local automation tool: allow all origins, methods, and headers.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class HuntRequest(BaseModel):
    niche: str


def build_source_urls(niche: str) -> list[dict]:
    """Build the exact ten Decodo discovery-source payloads for a niche.

    Six Google Search queries first, then Amazon, Reddit, TikTok Shop, and
    YouTube sources, always in this order. No network calls are made here;
    Phase 4 sends these payloads to Decodo.
    """
    google_queries = [
        f"viral {niche} products",
        f"problem solving {niche} products",
        f"TikTok {niche} gadgets",
        f"Amazon best selling {niche} under $50",
        f"lightweight {niche} products easy to ship",
        f"{niche} accessories under $50",
    ]

    sources: list[dict] = []

    for index, query in enumerate(google_queries, start=1):
        sources.append(
            {
                "source": f"Google Search {index}",
                "payload": {
                    "target": "google_search",
                    "query": query,
                    "headless": "html",
                    "parse": True,
                    "page_count": 1,
                    "google_results_language": "en",
                },
            }
        )

    sources.append(
        {
            "source": "Amazon Search",
            "payload": {
                "target": "amazon_search",
                "query": f"{niche} under $50",
                "page_from": "1",
                "parse": True,
            },
        }
    )

    sources.append(
        {
            "source": "Reddit Search",
            "payload": {
                "target": "universal",
                "url": (
                    "https://www.reddit.com/search.json"
                    f"?q={quote_plus(google_queries[0])}"
                    "&sort=relevance&t=year&limit=25"
                ),
            },
        }
    )

    sources.append(
        {
            "source": "TikTok Shop Search",
            "payload": {
                "target": "tiktok_shop_search",
                "query": niche,
                "parse": True,
            },
        }
    )

    sources.append(
        {
            "source": "YouTube Search",
            "payload": {
                "target": "youtube_search",
                "query": f"viral {niche} products TikTok",
            },
        }
    )

    return sources


def scrape_with_decodo_payload(source_name: str, payload: dict) -> dict:
    """Send one Decodo scrape request for a source payload.

    Posts the payload directly as JSON (never wrapped in another "payload"
    key). Failures — request errors, timeouts, non-2xx responses, and
    invalid JSON — are caught here and returned as an "error" entry so a
    single bad source can never crash the hunt path.
    """
    try:
        response = http.post(
            DECODO_API_URL,
            json=payload,
            headers={
                "accept": "application/json",
                "content-type": "application/json",
                "authorization": f"Basic {DECODO_AUTH_TOKEN}",
            },
            timeout=(10, DECODO_REQUEST_TIMEOUT),
        )
        response.raise_for_status()
        data = response.json()
        return {"source": source_name, "request": payload, "data": data}
    except Exception as error:
        return {"source": source_name, "request": payload, "error": str(error)}


def scrape_with_decodo(niche: str, logger=None) -> str:
    """Scrape all ten discovery sources concurrently via Decodo.

    Runs every payload from build_source_urls(niche) through a thread pool
    while preserving source order in the results. Returns a JSON string with
    one entry per attempted source; individual failures stay in the results
    as error entries instead of aborting the run.
    """
    sources = build_source_urls(niche)
    max_workers = max(1, min(len(sources), DECODO_MAX_WORKERS))

    if logger:
        logger(f"Discovery started: scraping {len(sources)} sources")

    def _scrape(source: dict) -> dict:
        result = scrape_with_decodo_payload(source["source"], source["payload"])
        if logger:
            if "error" in result:
                logger(f"Discovery failed for {result['source']}: {result['error']}")
            else:
                logger(f"Discovery succeeded for {result['source']}")
        return result

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        results = list(executor.map(_scrape, sources))

    return json.dumps(results)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/hunt")
def hunt(request: HuntRequest):
    # Phase 4: real concurrent Decodo discovery; later phases add screening,
    # ranking, and supplier sourcing on top of these raw results.
    discovery_data = json.loads(scrape_with_decodo(request.niche))
    return {
        "niche": request.niche,
        "message": "Discovery scraped via Decodo; ranking pipeline arrives in later phases",
        "initial_products": [],
        "final_products": [],
        "supplier_summary": {},
        "supplier_data": [],
        "discovery_summary": [],
        "discovery_data": discovery_data,
        "ranking_warnings": [],
    }


if __name__ == "__main__":
    uvicorn.run("api:app", host="127.0.0.1", port=BACKEND_PORT, reload=True)
