import requests
import json
import argparse
from datetime import datetime

SERP_API_KEY = "2324e806dec317b866340513d6739a527e3ce903d2c9690b3f4524eb7953b5b8"
SERP_BASE_URL = "https://serpapi.com/search"


def collect_reviews(business_name: str, location: str, category: str, max_reviews: int = 20):
    """
    Collect Google Maps reviews for a specific business.

    Args:
        business_name : Name of the business (e.g. "Subway")
        location      : City / region / country (e.g. "Sydney")
        category      : Type of business (e.g. "restaurant", "hotel", "bar")
        max_reviews   : Max number of reviews to return (max 20 per request on free tier)

    Returns:
        List of standardized review dicts
    """

    print(f"\n Searching Google Maps for: '{business_name}'")
    print(f"   Location : {location}")
    print(f"   Category : {category}\n")

    # ── Step 1: Search Google Maps to find the business and get its data_id ──
    # NOTE: data_id is required for the reviews API (not place_id)
    search_params = {
        "engine":  "google_maps",
        "q":       f"{business_name} {category} {location}",
        "type":    "search",
        "hl":      "en",
        "api_key": SERP_API_KEY,
    }

    search_response = requests.get(SERP_BASE_URL, params=search_params, timeout=30)

    if search_response.status_code != 200:
        print(f"  Error searching Google Maps: {search_response.status_code}")
        print(f"  {search_response.text[:300]}")
        return []

    search_data   = search_response.json()
    local_results = search_data.get("local_results", [])

    if not local_results:
        print(f"  No businesses found for '{business_name}' in '{location}'")
        return []

    # Pick the first (most relevant) result
    business      = local_results[0]
    data_id       = business.get("data_id", "")       # ← this is what reviews API needs
    place_id      = business.get("place_id", "")      # kept for reference only
    biz_title     = business.get("title", business_name)
    biz_addr      = business.get("address", "")
    biz_rating    = business.get("rating", None)
    biz_rev_count = business.get("reviews", None)

    print(f"  Found    : {biz_title}")
    print(f"  Address  : {biz_addr}")
    print(f"  Rating   : {biz_rating} ({biz_rev_count} total reviews on Google Maps)")
    print(f"  data_id  : {data_id}\n")

    if not data_id:
        print("  Could not find data_id — cannot fetch reviews.")
        return []

    # ── Step 2: Fetch reviews using data_id ──
    reviews_params = {
        "engine":   "google_maps_reviews",
        "data_id":  data_id,           # ← correct parameter (not place_id)
        "hl":       "en",
        "sort_by":  "newestFirst",
        # NOTE: num cannot be set on initial page — API always returns 8 results first page
        "api_key":  SERP_API_KEY,
    }

    reviews_response = requests.get(SERP_BASE_URL, params=reviews_params, timeout=30)

    if reviews_response.status_code != 200:
        print(f"  Error fetching reviews: {reviews_response.status_code}")
        try:
            print(f"  {reviews_response.json()}")
        except Exception:
            print(f"  {reviews_response.text[:300]}")
        return []

    reviews_data = reviews_response.json()
    raw_reviews  = reviews_data.get("reviews", [])

    print(f"  Fetched {len(raw_reviews)} reviews\n")

    if not raw_reviews:
        print("  No reviews returned.")
        return []

    # ── Step 3: Standardize into our data model ──
    standardized = []
    for review in raw_reviews:
        standardized.append({
            "id":        f"gmaps_{abs(hash(review.get('review_id', review.get('date', '') + review.get('user', {}).get('name', ''))))}",
            "source":    "google_maps_reviews",
            "publisher": "Google Maps",
            "timestamp": review.get("iso_date", review.get("date", "")),
            "query": {
                "business_name": business_name,
                "location":      location,
                "category":      category,
            },
            "business": {
                "name":           biz_title,
                "address":        biz_addr,
                "overall_rating": biz_rating,
                "total_reviews":  biz_rev_count,
                "place_id":       place_id,
                "data_id":        data_id,
            },
            "title": "",
            "body":  review.get("snippet", ""),
            "url":   f"https://www.google.com/maps/place/?q=place_id:{place_id}",
            "data_type": "score_only" if not review.get("snippet") else "text_review",
            "metadata": {
                "author":      review.get("user", {}).get("name", "Anonymous"),
                "rating":      review.get("rating", None),
                "likes":       review.get("likes", 0),
                "review_date": review.get("date", ""),
            },
        })

    return standardized


# ── CLI entry point ──────────────────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Collect Google Maps reviews for a hospitality business.")
    parser.add_argument("business",   nargs="?", help='Business name e.g. "Subway"')
    parser.add_argument("--location", help="City / region / country")
    parser.add_argument("--category", help="Business type e.g. restaurant, hotel, bar")
    parser.add_argument("--max",      type=int, default=20, help="Max reviews to fetch (default 20)")
    parser.add_argument("--out",      default="reviews_results.json")
    args = parser.parse_args()

    business_name = (args.business  or "").strip() or input("Enter business name: ").strip()
    location      = (args.location  or "").strip() or input("Enter location (city / country): ").strip()
    category      = (args.category  or "").strip() or input("Enter category (restaurant / hotel / bar): ").strip()

    if not business_name: raise SystemExit("  Business name cannot be empty.")
    if not location:      raise SystemExit("  Location cannot be empty.")
    if not category:      raise SystemExit("  Category cannot be empty.")

    results = collect_reviews(business_name, location, category, max_reviews=args.max)

    for i, review in enumerate(results, 1):
        rating = review["metadata"]["rating"]
        stars  = "★" * int(rating) + "☆" * (5 - int(rating)) if rating else "No rating"
        print(f"Review {i}:")
        print(f"  Business  : {review['business']['name']}")
        print(f"  Author    : {review['metadata']['author']}")
        print(f"  Rating    : {stars} ({rating}/5)")
        print(f"  Date      : {review['metadata']['review_date']}")
        body_preview = review['body'][:150] + "..." if len(review['body']) > 150 else review['body']
        print(f"  Review    : {body_preview if body_preview else 'No text'}")
        print()

    with open(args.out, "w") as f:
        json.dump(results, f, indent=2)
    print(f"  {len(results)} reviews saved to {args.out}")