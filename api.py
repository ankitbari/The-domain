"""AI Product Hunter Automation - FastAPI backend.

Local automation API for dropshipping product discovery, safety/quality
screening, and supplier-aware ranking. Phase 2: first working version with
a health check and a placeholder hunt endpoint.
"""

import os

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


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/hunt")
def hunt(request: HuntRequest):
    # Temporary placeholder; the real pipeline lands in later phases.
    return {
        "niche": request.niche,
        "message": "AI Product Hunter Automation placeholder",
        "initial_products": [],
        "final_products": [],
        "supplier_summary": {},
        "supplier_data": [],
        "discovery_summary": [],
        "discovery_data": [],
        "ranking_warnings": [],
    }


if __name__ == "__main__":
    uvicorn.run("api:app", host="127.0.0.1", port=BACKEND_PORT, reload=True)
