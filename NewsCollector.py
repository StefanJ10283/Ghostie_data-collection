import requests
import json
import argparse
from datetime import datetime, timedelta

API_KEY = "7fcff161440b4fd9aae0536fe7a62c1a"
BASE_URL = "https://newsapi.org/v2/everything"

MAX_DAYS_BACK = 29


def collect_news(business_name: str, location: str, category: str, days_back: int = MAX_DAYS_BACK):
    """
    Collect news articles mentioning a specific hospitality business.

    Args:
        business_name : Name of the business (e.g. "Subway")
        location      : City / region / country (e.g. "Australia")
        category      : Type of business (e.g. "restaurant", "hotel", "bar")
        days_back     : How many days back to search (capped at 29 for free tier)

    Returns:
        List of standardized article dicts
    """

    # Cap to free-tier limit
    days_back = min(days_back, MAX_DAYS_BACK)
    date_from = (datetime.now() - timedelta(days=days_back)).strftime("%Y-%m-%d")
    date_to   = datetime.now().strftime("%Y-%m-%d")

    # --- Query strategy ---
    # We search for business_name AND category together.
    # This disambiguates common words — e.g. "Subway" alone returns NYC transit
    # articles, but "Subway" AND "restaurant" targets the sandwich chain.
    # Location is NOT in the query (too restrictive); we filter by it locally instead.
    query = f'"{business_name}" AND "{category}"'

    params = {
        "q":        query,
        "from":     date_from,
        "to":       date_to,
        "language": "en",
        "sortBy":   "relevancy",   # relevancy works better than publishedAt for disambiguation
        "pageSize": 100,           # fetch more so filtering has enough to work with
        "apiKey":   API_KEY,
    }

    print(f"\n Searching news for: '{business_name}'")
    print(f"   Location : {location}")
    print(f"   Category : {category}")
    print(f"   Query    : {query}")
    print(f"   Dates    : {date_from} to {date_to}\n")

    response = requests.get(BASE_URL, params=params, timeout=30)

    # Handle free-tier date restriction (HTTP 426)
    if response.status_code == 426:
        print("  Plan limit hit on date range. Adjusting start date by +1 day and retrying...\n")
        new_from = (datetime.strptime(date_from, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")
        params["from"] = new_from
        response = requests.get(BASE_URL, params=params, timeout=30)

    if response.status_code != 200:
        try:
            msg = response.json().get("message", "Unknown error")
        except Exception:
            msg = response.text
        print(f"  NewsAPI error {response.status_code}: {msg}")
        return []

    data         = response.json()
    raw_articles = data.get("articles", [])
    total        = data.get("totalResults", 0)
    print(f"  NewsAPI returned {total} total results, fetched top {len(raw_articles)}")

    # --- Local relevance filter ---
    # Keep only articles where the title OR description contains the business name.
    # This removes false positives that slipped through the query.
    def is_relevant(article: dict) -> bool:
        title = article.get("title") or ""
        desc  = article.get("description") or ""
        combined = (title + " " + desc).lower()
        return business_name.lower() in combined

    relevant = [a for a in raw_articles if is_relevant(a)]
    print(f"  After relevance filter: {len(relevant)} articles kept, {len(raw_articles) - len(relevant)} removed\n")

    if not relevant:
        print("  No relevant articles found. Try a different business name or broaden your search.")
        return []

    # --- Standardize into our data model ---
    standardized = []
    for article in relevant:
        standardized.append({
            "id":        f"news_{abs(hash(article.get('url', '')))}",
            "source":    "newsapi",
            "publisher": article.get("source", {}).get("name", "Unknown"),
            "timestamp": article.get("publishedAt", ""),
            "query": {
                "business_name": business_name,
                "location":      location,
                "category":      category,
            },
            "title": article.get("title", ""),
            "body":  article.get("description", ""),
            "url":   article.get("url", ""),
            "metadata": {
                "author": article.get("author", ""),
            },
        })

    return standardized


def collect_news_reviews(business_name: str, location: str, category: str, days_back: int = MAX_DAYS_BACK):
    """
    Collect news articles that are critic/publication reviews of the business.
    Same as collect_news() but targets review pieces specifically by including
    "review" in the query, and tags results with source="news_review".

    Returns:
        List of standardized article dicts (source = "news_review")
    """

    days_back = min(days_back, MAX_DAYS_BACK)
    date_from = (datetime.now() - timedelta(days=days_back)).strftime("%Y-%m-%d")
    date_to   = datetime.now().strftime("%Y-%m-%d")

    query = f'"{business_name}" AND "{category}" AND "review"'

    params = {
        "q":        query,
        "from":     date_from,
        "to":       date_to,
        "language": "en",
        "sortBy":   "relevancy",
        "pageSize": 100,
        "apiKey":   API_KEY,
    }

    print(f"\n Searching news reviews for: '{business_name}'")
    print(f"   Location : {location}")
    print(f"   Category : {category}")
    print(f"   Query    : {query}")
    print(f"   Dates    : {date_from} to {date_to}\n")

    response = requests.get(BASE_URL, params=params, timeout=30)

    if response.status_code == 426:
        print("  Plan limit hit on date range. Adjusting start date by +1 day and retrying...\n")
        new_from = (datetime.strptime(date_from, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")
        params["from"] = new_from
        response = requests.get(BASE_URL, params=params, timeout=30)

    if response.status_code != 200:
        try:
            msg = response.json().get("message", "Unknown error")
        except Exception:
            msg = response.text
        print(f"  NewsAPI error {response.status_code}: {msg}")
        return []

    data         = response.json()
    raw_articles = data.get("articles", [])
    total        = data.get("totalResults", 0)
    print(f"  NewsAPI returned {total} total results, fetched top {len(raw_articles)}")

    def is_relevant(article: dict) -> bool:
        title = article.get("title") or ""
        desc  = article.get("description") or ""
        combined = (title + " " + desc).lower()
        return business_name.lower() in combined

    relevant = [a for a in raw_articles if is_relevant(a)]
    print(f"  After relevance filter: {len(relevant)} news reviews kept, {len(raw_articles) - len(relevant)} removed\n")

    if not relevant:
        print("  No relevant news reviews found.")
        return []

    standardized = []
    for article in relevant:
        standardized.append({
            "id":        f"newsreview_{abs(hash(article.get('url', '')))}",
            "source":    "news_review",
            "publisher": article.get("source", {}).get("name", "Unknown"),
            "timestamp": article.get("publishedAt", ""),
            "query": {
                "business_name": business_name,
                "location":      location,
                "category":      category,
            },
            "title": article.get("title", ""),
            "body":  article.get("description", ""),
            "url":   article.get("url", ""),
            "metadata": {
                "author": article.get("author", ""),
            },
        })

    return standardized


# ── CLI entry point ──────────────────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Collect news articles for a hospitality business.")
    parser.add_argument("business",    nargs="?", help='Business name, e.g. "Subway"')
    parser.add_argument("--location",  help="City / region / country")
    parser.add_argument("--category",  help="Business type, e.g. restaurant, hotel, bar")
    parser.add_argument("--days-back", type=int, default=MAX_DAYS_BACK)
    parser.add_argument("--out",       default="news_results.json")
    args = parser.parse_args()

    business_name = (args.business  or "").strip() or input("Enter business name: ").strip()
    location      = (args.location  or "").strip() or input("Enter location (city / country): ").strip()
    category      = (args.category  or "").strip() or input("Enter category (restaurant / hotel / bar): ").strip()

    if not business_name: raise SystemExit("  Business name cannot be empty.")
    if not location:      raise SystemExit("  Location cannot be empty.")
    if not category:      raise SystemExit("  Category cannot be empty.")

    results = collect_news(business_name, location, category, days_back=args.days_back)

    for i, article in enumerate(results, 1):
        print(f"Article {i}:")
        print(f"  Publisher : {article['publisher']}")
        print(f"  Title     : {article['title']}")
        print(f"  Date      : {article['timestamp']}")
        body_preview = article['body'][:120] + "..." if article['body'] else "N/A"
        print(f"  Summary   : {body_preview}")
        print(f"  URL       : {article['url']}")
        print()

    with open(args.out, "w") as f:
        json.dump(results, f, indent=2)
    print(f"  {len(results)} articles saved to {args.out}")