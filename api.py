"""AI Product Hunter Automation - FastAPI backend.

Local automation API for dropshipping product discovery, safety/quality
screening, and supplier-aware ranking. Phase 5: compact and normalize the
Phase 4 Decodo discovery data — parse responses, trim them to debug-sized
summaries, extract and deduplicate normalized product candidates, and score
each candidate with a deterministic, local, evidence-based viral score.
"""

import copy
import json
import math
import os
import re
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import quote_plus, urljoin

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

    # Phase 5: successful entries are trimmed to compact debug data (12k
    # character limit for unstructured text) before being returned, so the
    # hunt response never carries full large HTML documents.
    return json.dumps([trim_decodo_result(result, max_content_chars=12000) for result in results])


# ---------------------------------------------------------------------------
# Phase 5: content parsing, compaction, extraction, dedup, local viral score
# ---------------------------------------------------------------------------

# Field aliases recognized while walking parsed Decodo content. Keys are
# matched case-insensitively against these lowercase alias sets.
TITLE_ALIASES = ("product_title", "product_name", "title", "name")
PRICE_ALIASES = ("price", "current_price", "sale_price", "original_price", "price_lower", "price_min")
CURRENCY_ALIASES = ("currency", "price_currency", "currency_code", "symbol")
URL_ALIASES = ("url", "link", "product_url", "product_link", "absolute_url", "relative_url", "canonical_url", "item_url")
IMAGE_ALIASES = ("image", "images", "image_url", "images_base_uri", "thumbnail", "thumbnail_image", "thumbnail_url", "primary_image", "main_image", "picture", "picture_url", "img", "src")
RATING_ALIASES = ("rating", "star_rating", "average_rating", "overall_rating", "rating_value")
REVIEWS_ALIASES = ("reviews", "review_count", "num_reviews", "ratings_total", "total_reviews", "no_of_reviews")
SALES_ALIASES = ("sales", "sales_volume", "number_sold", "bought_in_past_month", "orders", "order_count", "purchases")
BADGES_ALIASES = ("badges", "badge", "label", "labels")
ASIN_ALIASES = ("asin", "product_asin", "id_asin")

# A candidate needs a nonblank title plus at least one of these signals.
PRODUCT_SIGNAL_KEYS = PRICE_ALIASES + RATING_ALIASES + REVIEWS_ALIASES + SALES_ALIASES + IMAGE_ALIASES

_BADGE_TEXT_RE = re.compile(r"best\s*seller|amazon'?s\s*choice", re.IGNORECASE)
_NUMBER_RE = re.compile(r"\d[\d,.]*")


def stringify_decodo_content(content) -> str:
    """Render any Decodo content value as plain text for length accounting."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, (dict, list)):
        try:
            return json.dumps(content, ensure_ascii=False, default=str)
        except (TypeError, ValueError):
            return str(content)
    return str(content)


def parse_decodo_content(content):
    """Parse string content as JSON when possible.

    Ordinary HTML, Markdown, and plain text fail JSON parsing and are left
    as strings; dict/list content passes through untouched. Never raises.
    """
    if isinstance(content, str):
        stripped = content.strip()
        if stripped[:1] in ("{", "["):
            try:
                return json.loads(stripped)
            except (json.JSONDecodeError, ValueError):
                return content
        return content
    return content


def get_parsed_results(content):
    """Return the actual product-ish payload inside a Decodo parser envelope.

    Supports both parser layouts: first reads ``content["results"]``
    (defaulting to the content itself). If that value is not a dictionary it
    is returned directly (a bare product list or raw text). If it is a
    dictionary whose nested ``results`` field is also a dictionary, keep
    descending until hitting an actual record or a non-dictionary — the outer
    envelope must never be treated as a product.
    """
    parsed = parse_decodo_content(content)
    if not isinstance(parsed, dict):
        return parsed
    current = parsed.get("results", parsed)
    while isinstance(current, dict) and isinstance(current.get("results"), dict):
        current = current["results"]
    return current


def _truncate_text(value: str, max_chars: int) -> str:
    """Character-truncate only unstructured text; keep short strings intact."""
    if len(value) <= max_chars:
        return value
    return value[:max_chars] + "...[truncated]"


def _trim_scalars(node, max_content_chars: int):
    """Recursively truncate long strings inside freshly built trim structures.

    Parsed structured JSON stays structured — only unstructured text values
    (HTML/Markdown/plain text) are character-truncated.
    """
    if isinstance(node, dict):
        return {key: _trim_scalars(value, max_content_chars) for key, value in node.items()}
    if isinstance(node, list):
        return [_trim_scalars(value, max_content_chars) for value in node]
    if isinstance(node, str):
        return _truncate_text(node, max_content_chars)
    return node


def _first_present(record: dict, keys: tuple):
    for key in keys:
        if key in record and record[key] not in (None, "", [], {}):
            return record[key]
    return None


def _compact_amazon_product(product: dict) -> dict:
    """Keep only the useful Amazon fields needed for debugging/extraction."""
    compact = {
        key: product[key]
        for key in ("position", "title", "price", "currency", "rating", "reviews", "sales", "badges", "asin")
        if key in product
    }
    url = _first_present(product, URL_ALIASES)
    if isinstance(url, str) and url:
        compact["url"] = _normalize_amazon_url(url)
    image = _extract_image(product)
    if image:
        compact["image"] = image
    return compact


def trim_decodo_result(result: dict, max_content_chars: int = 3500) -> dict:
    """Deep-copy then compact one discovery result entry for safe transport.

    ``discovery_data`` is compacted debug data, not a byte-for-byte raw
    response: full large HTML documents are never exposed. Amazon results
    keep at most 25 organic products with useful fields only; Google results
    preserve query/page/status plus bounded AI overviews, organic results,
    related questions, and shopping/product sections (object-valued sections
    are preserved without blind flattening). Error entries pass through
    unchanged apart from the deep copy.
    """
    trimmed = copy.deepcopy(result)
    if not isinstance(trimmed, dict) or "data" not in trimmed:
        return trimmed

    source_name = str(trimmed.get("source", ""))
    data = trimmed["data"]
    inner = data.get("content", data) if isinstance(data, dict) else data
    parsed = get_parsed_results(inner)

    if isinstance(parsed, dict):
        body = _cap_record_lists(parsed, source_name)
        trimmed["data"] = _trim_scalars(body, max_content_chars)
    else:
        trimmed["data"] = _truncate_text(stringify_decodo_content(parsed), max_content_chars)

    return trimmed


def _cap_record_lists(parsed: dict, source_name: str) -> dict:
    """Bound record lists and keep only useful fields, per source type.

    Amazon: at most 25 organic products, useful fields only (position,
    title, price/currency, rating, reviews/sales, badges, ASIN, normalized
    URL, image). Google: preserve query/page/status plus up to 3 AI
    overviews, 10 organic results, 10 related questions, and up to 25
    records in shopping/product-style sections; object-valued sections are
    preserved without blind flattening. Other sources pass through as-is
    apart from scalar truncation elsewhere in the trim step.
    """
    lower_source = source_name.lower()

    def cap_section(value):
        if isinstance(value, list):
            return [
                _compact_amazon_product(item) if is_amazon and isinstance(item, dict) else item
                for item in value[:25]
            ]
        if isinstance(value, dict):
            # Object-valued section: recurse into its record lists too.
            return {key: cap_list_section(key, child) for key, child in value.items()}
        return value

    def cap_list_section(key, value):
        if key in record_keys:
            return cap_section(value)
        if isinstance(value, dict):
            return {k: cap_list_section(k, v) for k, v in value.items()}
        return value

    if "amazon" in lower_source:
        is_amazon = True
        record_keys = {"products", "results", "items"}
        organic = parsed.get("products")
        capped = {
            key: cap_section(organic) if key == "products" and isinstance(organic, list) else value
            for key, value in parsed.items()
        }
        return capped

    if "google" in lower_source:
        is_amazon = False
        record_keys = {"shopping", "products", "items", "shopping_results", "local_results", "inline_images"}
        keep = {}
        for key in (
            "query", "page", "status", "language", "location", "country",
            "number_of_results", "answer", "ai_overview", "organic",
            "related_questions", "shopping", "products", "items",
            "local_results", "knowledge_graph", "inline_images", "personally_annotated",
        ):
            if key not in parsed:
                continue
            value = parsed[key]
            if key == "ai_overview" and isinstance(value, list):
                value = value[:3]
            elif key == "organic" and isinstance(value, list):
                value = value[:10]
            elif key == "related_questions" and isinstance(value, list):
                value = value[:10]
            elif key in record_keys:
                value = cap_section(value)
            keep[key] = value
        return keep if keep else parsed

    return dict(parsed)


def compact_parsed_content(source_name: str, content) -> dict:
    """Compact one source's raw content into a small, safe debug structure."""
    parsed = get_parsed_results(content)
    if isinstance(parsed, dict):
        records = parsed.get("products")
        count = len(records) if isinstance(records, list) else 0
        return {
            "kind": "object",
            "keys": sorted(str(key) for key in parsed)[:40],
            "record_count": count,
            "preview": _truncate_text(stringify_decodo_content(parsed), 600),
        }
    if isinstance(parsed, list):
        return {
            "kind": "list",
            "record_count": len(parsed),
            "preview": _truncate_text(stringify_decodo_content(parsed), 600),
        }
    return {
        "kind": "text",
        "record_count": 0,
        "preview": _truncate_text(stringify_decodo_content(parsed), 600),
    }


def summarize_decodo_result(result: dict) -> dict:
    """Build one compact summary row per discovery source."""
    source = str(result.get("source", "")) if isinstance(result, dict) else ""
    error = str(result["error"]) if isinstance(result, dict) and "error" in result else ""
    data = result.get("data") if isinstance(result, dict) else None

    status_code = data.get("status_code") if isinstance(data, dict) else None
    parser_status = data.get("parser", {}).get("status") if isinstance(data, dict) and isinstance(data.get("parser"), dict) else None

    if isinstance(data, dict):
        content = data.get("content", data)
        parsed = get_parsed_results(content)
        if isinstance(parsed, dict):
            products = parsed.get("products")
            response_count = len(products) if isinstance(products, list) else len(parsed)
        elif isinstance(parsed, list):
            response_count = len(parsed)
        else:
            response_count = 1 if parsed else 0
        content_chars = len(stringify_decodo_content(content))
    else:
        parsed = None
        response_count = 0
        content_chars = 0

    product_count = len(extract_products([result], limit=25))

    parts = []
    if error:
        parts.append("error")
    else:
        parts.append("ok")
    if status_code is not None:
        parts.append(f"http:{status_code}")
    if parser_status:
        parts.append(f"parser:{parser_status}")
    parts.append(f"records:{response_count}")
    parts.append(f"products:{product_count}")
    parts.append(f"chars:{content_chars}")

    return {
        "source": source,
        "error": error,
        "product_count": product_count,
        "response_count": response_count,
        "status_code": status_code,
        "parser_status": parser_status,
        "content_chars": content_chars,
        "status": " | ".join(parts),
    }


def _is_blank(value) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def _to_number(value):
    """Coerce "$12.99", "1 1/2", "1,234", "4.5 stars", 39.99 to a float."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, dict):
        for key in ("value", "amount", "min", "max", "price"):
            number = _to_number(value.get(key))
            if number is not None:
                return number
        return None
    if not isinstance(value, str):
        return None
    text = value.strip()
    fraction = re.match(r"^(\d+)\s+(\d+)/(\d+)$", text)
    if fraction:
        whole, numerator, denominator = fraction.groups()
        try:
            return float(whole) + float(numerator) / float(denominator)
        except ZeroDivisionError:
            return None
    match = _NUMBER_RE.search(text)
    if not match:
        return None
    token = match.group().replace(",", "")
    if token.endswith("."):
        token = token[:-1]
    try:
        return float(token)
    except ValueError:
        return None


def _extract_price(record: dict):
    price = _first_present(record, PRICE_ALIASES)
    if isinstance(price, dict):
        numeric = _to_number(price)
        currency = price.get("currency") or price.get("symbol")
        return numeric, currency
    return _to_number(price), None


def _extract_image(record: dict):
    """Pull one image URL even when images nest inside lists or objects."""
    for key in IMAGE_ALIASES:
        value = record.get(key)
        found = _image_from_value(value)
        if found:
            return found
    return None


def _image_from_value(value):
    if isinstance(value, str):
        return value.strip() or None
    if isinstance(value, list):
        for item in value:
            found = _image_from_value(item)
            if found:
                return found
        return None
    if isinstance(value, dict):
        for key in ("url", "link", "src", "image", "image_url", "thumbnail", "value"):
            found = _image_from_value(value.get(key))
            if found:
                return found
    return None


def _normalize_amazon_url(url) -> str:
    """Expand relative Amazon product URLs to absolute Amazon URLs."""
    if not isinstance(url, str) or not url.strip():
        return ""
    url = url.strip()
    if url.startswith("//"):
        return "https:" + url
    if url.startswith(("http://", "https://")):
        return url
    if url.startswith("/"):
        return urljoin("https://www.amazon.com", url)
    return urljoin("https://www.amazon.com/", url)


def _collect_evidence(record: dict) -> list:
    evidence = []
    title = str(record.get("title", "")).strip()
    if title:
        evidence.append(title[:120])
    badges = record.get("badges")
    if isinstance(badges, list):
        evidence.extend(str(badge).strip()[:80] for badge in badges if not _is_blank(badge))
    elif not _is_blank(badges):
        evidence.append(str(badges).strip()[:80])
    return evidence


def _scan_candidate(record: dict):
    """Return a normalized candidate dict if the record qualifies as a product."""
    title = _first_present(record, TITLE_ALIASES)
    if _is_blank(title):
        return None
    has_signal = any(
        not _is_blank(record.get(key)) for key in PRODUCT_SIGNAL_KEYS if isinstance(key, str)
    )
    if not has_signal:
        return None

    price, raw_currency = _extract_price(record)
    currency = _first_present(record, CURRENCY_ALIASES) or raw_currency
    url = _normalize_amazon_url(_first_present(record, URL_ALIASES) or "")
    image = _extract_image(record)
    rating = _to_number(_first_present(record, RATING_ALIASES))
    reviews = _to_number(_first_present(record, REVIEWS_ALIASES))
    sales = _to_number(_first_present(record, SALES_ALIASES))
    asin = _first_present(record, ASIN_ALIASES)

    return {
        "title": str(title).strip(),
        "price": price,
        "currency": str(currency).strip() if not _is_blank(currency) else None,
        "url": url or None,
        "image": image,
        "rating": rating,
        "reviews": reviews,
        "sales": sales,
        "asin": str(asin).strip() if not _is_blank(asin) else None,
        "evidence": _collect_evidence(record),
    }


def _walk_records(node):
    """Yield every dict inside parsed content; mark direct children of a
    'products'/'results'-style container so nested attribute dicts (e.g.
    {"price": {"value": ...}}) are not mistaken for separate products."""
    def _walk(value, is_record):
        if isinstance(value, dict):
            if is_record:
                yield value
            for key, child in value.items():
                nested_is_record = key in ("products", "results", "organic", "items", "shopping")
                yield from _walk(child, nested_is_record)
        elif isinstance(value, list):
            for item in value:
                yield from _walk(item, True)

    yield from _walk(node, False)


def _dedupe_key(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", title.lower()).strip()


def _compute_viral_score(product: dict) -> int:
    """Deterministic, local, evidence-based score (Phase 5 baseline)."""
    score = 35
    price = product.get("price")
    if price is not None and 5 <= price <= 50:
        score += 12
    rating = product.get("rating")
    if rating is not None:
        score += min(15, round(rating * 3))
    volume_values = [v for v in (product.get("reviews"), product.get("sales")) if v is not None and v > 1]
    if volume_values:
        score += min(18, round(math.log10(max(volume_values)) * 5))
    if product.get("image"):
        score += 5
    if product.get("url"):
        score += 5
    evidence_text = " ".join(str(item) for item in product.get("evidence", []))
    if _BADGE_TEXT_RE.search(evidence_text):
        score += 10
    return min(100, score)


def extract_products(discovery_results: list, limit: int = 25) -> list:
    """Extract, normalize, deduplicate, and locally rank product candidates.

    Recursively walks dictionaries and lists inside parsed Decodo content.
    A candidate requires a nonblank title plus at least one product signal
    (price, rating, reviews, sales/orders, or image), so title-only
    navigation/search records are never emitted. Duplicates (matched on a
    normalized lowercase title) merge their source names and evidence and
    fill missing price/currency/url/image from later records. Returns up to
    ``limit`` unique candidates sorted by viral_score descending.
    """
    seen: dict = {}
    order: list = []

    for result in discovery_results or []:
        if not isinstance(result, dict) or "error" in result:
            continue
        source_name = str(result.get("source", "unknown"))
        data = result.get("data")
        content = data.get("content", data) if isinstance(data, dict) else data
        parsed = get_parsed_results(content)

        for record in _walk_records(parsed):
            candidate = _scan_candidate(record)
            if candidate is None:
                continue
            key = _dedupe_key(candidate["title"])
            if not key:
                continue
            if key in seen:
                existing = seen[key]
                if source_name not in existing["source"]:
                    existing["source"].append(source_name)
                for item in candidate["evidence"]:
                    if item not in existing["evidence"]:
                        existing["evidence"].append(item)
                if existing["price"] is None and candidate["price"] is not None:
                    existing["price"] = candidate["price"]
                if not existing["currency"] and candidate["currency"]:
                    existing["currency"] = candidate["currency"]
                if not existing["url"] and candidate["url"]:
                    existing["url"] = candidate["url"]
                if not existing["image"] and candidate["image"]:
                    existing["image"] = candidate["image"]
                if existing["rating"] is None and candidate["rating"] is not None:
                    existing["rating"] = candidate["rating"]
                if existing["reviews"] is None and candidate["reviews"] is not None:
                    existing["reviews"] = candidate["reviews"]
                if existing["sales"] is None and candidate["sales"] is not None:
                    existing["sales"] = candidate["sales"]
                continue
            seen[key] = {
                "product": candidate["title"],
                "source": [source_name],
                "price": candidate["price"],
                "currency": candidate["currency"],
                "url": candidate["url"],
                "image": candidate["image"],
                "rating": candidate["rating"],
                "reviews": candidate["reviews"],
                "sales": candidate["sales"],
                "asin": candidate["asin"],
                "evidence": list(candidate["evidence"]),
            }
            order.append(key)
            if len(order) >= limit:
                break
        if len(order) >= limit:
            break

    products = [seen[key] for key in order]
    for product in products:
        product["viral_score"] = _compute_viral_score(product)
    products.sort(key=lambda product: product["viral_score"], reverse=True)
    return products


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/hunt")
def hunt(request: HuntRequest):
    # Phase 5: scrape via Decodo, then compact, extract, deduplicate, and
    # locally score candidates. Screening (Laya), AI ranking, and supplier
    # sourcing arrive in later phases, so final/supplier fields stay empty.
    discovery_data = json.loads(scrape_with_decodo(request.niche))
    discovery_summary = [summarize_decodo_result(result) for result in discovery_data]
    initial_products = extract_products(discovery_data, limit=25)
    return {
        "niche": request.niche,
        "message": "Discovery scraped, compacted, and normalized; screening and ranking arrive in later phases",
        "initial_products": initial_products,
        "final_products": [],
        "supplier_summary": {},
        "supplier_data": [],
        "discovery_summary": discovery_summary,
        "discovery_data": discovery_data,
        "ranking_warnings": [],
    }


if __name__ == "__main__":
    uvicorn.run("api:app", host="127.0.0.1", port=BACKEND_PORT, reload=True)
