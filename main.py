from fastapi import FastAPI, HTTPException
from mangum import Mangum
from pydantic import BaseModel
from datetime import datetime
import json
import logging
import os
import re

import requests as http_requests

# Import our collectors
from NewsCollector import collect_news, collect_news_reviews
from ReviewCollector import collect_reviews

# ── Local storage folder ─────────────────────────────────────────────────────
# Results are saved here until S3 is ready.
# When S3 is set up, swap this section for a boto3 upload — everything else stays the same.
# Lambda's filesystem is read-only except /tmp; use /tmp when running on Lambda
RESULTS_DIR = "/tmp/collected_data" if os.environ.get("AWS_LAMBDA_FUNCTION_NAME") else "collected_data"
os.makedirs(RESULTS_DIR, exist_ok=True)


def save_locally(data: dict) -> str:
    """
    Save collected results to a local JSON file.
    Filename format: collected_data/{business}_{location}_{timestamp}.json
    Returns the filepath so it can be logged or returned in the response.
    """
    # Sanitize business name and location for use in filename
    safe_name     = re.sub(r"[^a-zA-Z0-9]", "_", data["business_name"]).lower()
    safe_location = re.sub(r"[^a-zA-Z0-9]", "_", data["location"]).lower()
    timestamp     = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    filename      = f"{safe_name}_{safe_location}_{timestamp}.json"
    filepath      = os.path.join(RESULTS_DIR, filename)

    with open(filepath, "w") as f:
        json.dump(data, f, indent=2)

    return filepath


RETRIEVAL_API_URL = "https://8dwmeuc3b1.execute-api.ap-southeast-2.amazonaws.com/Prod/store"


def post_to_retrieval_api(payload: dict) -> None:
    """
    POST collected data to the Retrieval API's /store endpoint.
    Logs a warning on failure but never raises — local file saving is unaffected.
    """
    body = {
        "business_name": payload["business_name"],
        "location":      payload["location"],
        "category":      payload["category"],
        "collected_at":  payload["collected_at"],
        "news_count":    payload["news_count"],
        "review_count":  payload["review_count"],
        "data":          payload["data"],
    }

    try:
        response = http_requests.post(RETRIEVAL_API_URL, json=body, timeout=10)
        if response.status_code < 200 or response.status_code >= 300:
            logging.warning(
                "Retrieval API /store returned %s: %s",
                response.status_code,
                response.text[:200],
            )
        else:
            print(f"  Posted to Retrieval API: {response.status_code}")
    except Exception as exc:
        logging.warning("Failed to POST to Retrieval API: %s", exc)


# ── App ──────────────────────────────────────────────────────────────────────

# When deployed on AWS Lambda behind API Gateway, the stage name (/Prod) is
# prepended to every path. FastAPI must know this so Swagger UI requests
# /Prod/openapi.json instead of /openapi.json (which API Gateway blocks with 403).
_root_path = "/Prod" if os.environ.get("AWS_LAMBDA_FUNCTION_NAME") else ""

app = FastAPI(
    title="Ghostie Data Collection API",
    description="Collects news articles and customer reviews for hospitality businesses to support sentiment analysis.",
    version="1.0.0",
    root_path=_root_path
)


# ── Request / Response Models ────────────────────────────────────────────────

class CollectRequest(BaseModel):
    business_name: str
    location: str
    category: str

    class Config:
        json_schema_extra = {
            "example": {
                "business_name": "Subway",
                "location": "Sydney",
                "category": "restaurant"
            }
        }

class CollectResponse(BaseModel):
    business_name: str
    location: str
    category: str
    collected_at: str
    total_results: int
    news_count: int
    news_review_count: int
    review_count: int
    score_only_count: int
    saved_to: str        # local filepath (will become S3 key later)
    data: list


# ── Routes ───────────────────────────────────────────────────────────────────

@app.get("/")
def root():
    return {
        "service": "Ghostie Data Collection API",
        "version": "1.0.0",
        "status":  "running",
        "endpoints": {
            "POST /collect": "Collect news and reviews for a business",
            "GET /health":   "Health check",
            "GET /results":  "List all saved result files"
        }
    }


@app.get("/health")
def health():
    return {"status": "healthy", "timestamp": datetime.utcnow().isoformat()}


@app.get("/results")
def list_results():
    """List all locally saved result files."""
    files = os.listdir(RESULTS_DIR)
    files = [f for f in files if f.endswith(".json")]
    files.sort(reverse=True)  # most recent first
    return {
        "count": len(files),
        "files": files
    }


@app.post("/collect", response_model=CollectResponse)
def collect(request: CollectRequest):
    """
    Collect news articles and customer reviews for a hospitality business.

    - Calls NewsAPI to get recent news articles mentioning the business
    - Calls NewsAPI again with "review" in the query to get critic/publication reviews
    - Calls SerpAPI Google Maps Reviews to get real customer reviews with star ratings
      (reviews with no text body are tagged data_type="score_only")
    - Saves combined results to a local JSON file (will be S3 once infrastructure is ready)
    - Returns combined results in a standardized format for downstream processing
    """

    business_name = request.business_name.strip()
    location      = request.location.strip()
    category      = request.category.strip()

    if not business_name:
        raise HTTPException(status_code=400, detail="business_name cannot be empty")
    if not location:
        raise HTTPException(status_code=400, detail="location cannot be empty")
    if not category:
        raise HTTPException(status_code=400, detail="category cannot be empty")

    print(f"\n[{datetime.utcnow().isoformat()}] Collect request: {business_name} | {location} | {category}")

    # ── Collect from all sources ─────────────────────────────────────────────
    news_results        = []
    news_review_results = []
    review_results      = []
    errors              = []

    try:
        print("  Fetching news articles...")
        news_results = collect_news(business_name, location, category)
        print(f"  Got {len(news_results)} news articles")
    except Exception as e:
        errors.append(f"NewsAPI error: {str(e)}")
        print(f"  NewsAPI failed: {e}")

    try:
        print("  Fetching news reviews (critic/publication reviews)...")
        news_review_results = collect_news_reviews(business_name, location, category)
        print(f"  Got {len(news_review_results)} news reviews")
    except Exception as e:
        errors.append(f"NewsAPI reviews error: {str(e)}")
        print(f"  NewsAPI reviews failed: {e}")

    try:
        print("  Fetching Google Maps reviews...")
        review_results = collect_reviews(business_name, location, category)
        print(f"  Got {len(review_results)} reviews")
    except Exception as e:
        errors.append(f"SerpAPI error: {str(e)}")
        print(f"  SerpAPI failed: {e}")

    # ── Combine results ──────────────────────────────────────────────────────
    combined = news_results + news_review_results + review_results

    if not combined:
        raise HTTPException(
            status_code=404,
            detail=f"No data found for '{business_name}' in '{location}'. Errors: {errors}"
        )

    score_only_count = sum(1 for r in review_results if r.get("data_type") == "score_only")

    # ── Build response payload ───────────────────────────────────────────────
    payload = {
        "business_name":    business_name,
        "location":         location,
        "category":         category,
        "collected_at":     datetime.utcnow().isoformat(),
        "total_results":    len(combined),
        "news_count":       len(news_results),
        "news_review_count": len(news_review_results),
        "review_count":     len(review_results),
        "score_only_count": score_only_count,
        "data":             combined,
    }

    # ── Save locally ─────────────────────────────────────────────────────────
    # TODO: replace save_locally() with S3 upload when Do In Kim sets up the bucket
    filepath = save_locally(payload)
    print(f"  Saved to: {filepath}")

    payload["saved_to"] = filepath

    # ── POST to Retrieval API ────────────────────────────────────────────────
    post_to_retrieval_api(payload)

    return payload


# ── Lambda handler (Mangum wraps FastAPI for AWS Lambda) ─────────────────────
handler = Mangum(app)


# ── Run locally ──────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
