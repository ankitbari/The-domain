"""AI Product Hunter Automation - FastAPI backend.

Local automation API for dropshipping product discovery, safety/quality
screening, and supplier-aware ranking. Phase 3: builds the exact ten Decodo
discovery-source payloads for a niche (no scraping calls yet).
"""

import os
from urllib.parse import quote_plus

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

load_dotenv()

BACKEND_PORT = 8000

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


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/hunt")
def hunt(request: HuntRequest):
    # Temporary placeholder; the real pipeline lands in later phases.
    return {
        "niche": request.niche,
        "message": "Discovery sources built; Decodo scraping arrives in Phase 4",
        "initial_products": [],
        "final_products": [],
        "supplier_summary": {},
        "supplier_data": [],
        "discovery_summary": [],
        "discovery_data": build_source_urls(request.niche),
        "ranking_warnings": [],
    }


if __name__ == "__main__":
    uvicorn.run("api:app", host="127.0.0.1", port=BACKEND_PORT, reload=True)
