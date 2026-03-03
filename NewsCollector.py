import requests
import json
import re
from datetime import datetime, timedelta

API_KEY = "7fcff161440b4fd9aae0536fe7a62c1a"
BASE_URL = "https://newsapi.org/v2/everything"
# NewsAPI plan limits vary; using 29 avoids an off-by-one on many free keys.
MAX_DAYS_BACK = 29

def collect_news(business_name: str, days_back: int = MAX_DAYS_BACK):
    """
    Collect news articles mentioning a specific business.
    
    Args:
        business_name: Name of the hospitality business to search for
        days_back: How many days back to search (default 29 on free plans)
    
    Returns:
        List of standardized article objects
    """

    # Calculate date range
    effective_days_back = min(days_back, MAX_DAYS_BACK)
    if effective_days_back != days_back:
        print(
            f" Requested {days_back} days, but capping to {MAX_DAYS_BACK} days "
            f"to match typical NewsAPI plan limits."
        )

    date_from = (datetime.now() - timedelta(days=effective_days_back)).strftime("%Y-%m-%d")
    date_to = datetime.now().strftime("%Y-%m-%d")

    # Build the request
    params = {
        "q": business_name,           # Search query
        "from": date_from,            # Start date
        "to": date_to,                # End date
        "language": "en",             # English articles only
        "sortBy": "publishedAt",      # Most recent first
        "pageSize": 20,               # Number of articles to return
        "apiKey": API_KEY
    }

    print(f"\n Searching news for: '{business_name}'")
    print(f" Date range: {date_from} to {date_to}")
    print(f" Calling NewsAPI...\n")

    # Make the API call
    response = requests.get(BASE_URL, params=params, timeout=30)

    # Check if request was successful
    if response.status_code != 200:
        try:
            msg = response.json().get("message")
        except ValueError:
            msg = response.text

        # If the plan blocks older articles, adjust to the earliest allowed date and retry once.
        if response.status_code == 426 and isinstance(msg, str):
            match = re.search(r"as far back as (\d{4}-\d{2}-\d{2})", msg)
            if match:
                allowed_from = match.group(1)
                if allowed_from:
                    try:
                        allowed_dt = datetime.strptime(allowed_from, "%Y-%m-%d")
                    except ValueError:
                        allowed_dt = None

                    # Some plans treat the earliest allowed date as exclusive; bump forward until accepted.
                    if allowed_dt is not None:
                        for bump_days in range(1, 4):
                            new_from = (allowed_dt + timedelta(days=bump_days)).strftime("%Y-%m-%d")
                            if new_from == params.get("from"):
                                continue

                            print(
                                f" Plan limit hit. Adjusting start date to {new_from} and retrying...\n"
                            )
                            params["from"] = new_from
                            response = requests.get(BASE_URL, params=params, timeout=30)
                            if response.status_code == 200:
                                data = response.json()
                                raw_articles = data.get("articles", [])
                                print(
                                    f" Found {data.get('totalResults', 0)} total articles, returning top {len(raw_articles)}\n"
                                )

                                standardized = []
                                for article in raw_articles:
                                    standardized.append({
                                        "id": f"news_{hash(article.get('url', ''))}",
                                        "source": "newsapi",
                                        "publisher": article.get("source", {}).get("name", "Unknown"),
                                        "timestamp": article.get("publishedAt", ""),
                                        "query": business_name,
                                        "title": article.get("title", ""),
                                        "body": article.get("description", ""),
                                        "url": article.get("url", ""),
                                        "metadata": {
                                            "author": article.get("author", ""),
                                        }
                                    })

                                return standardized

                            try:
                                msg = response.json().get("message")
                            except ValueError:
                                msg = response.text

                            if response.status_code != 426:
                                break

        print(f"Error: {response.status_code} - {msg}")
        return []

    data = response.json()
    raw_articles = data.get("articles", [])
    print(f" Found {data.get('totalResults', 0)} total articles, returning top {len(raw_articles)}\n")

    # Standardize into our data model
    standardized = []
    for article in raw_articles:
        standardized.append({
            "id": f"news_{hash(article.get('url', ''))}",
            "source": "newsapi",
            "publisher": article.get("source", {}).get("name", "Unknown"),
            "timestamp": article.get("publishedAt", ""),
            "query": business_name,
            "title": article.get("title", ""),
            "body": article.get("description", ""),   # Free tier only gives description, not full text
            "url": article.get("url", ""),
            "metadata": {
                "author": article.get("author", ""),
            }
        })

    return standardized


# --- Run it ---
if __name__ == "__main__":
    # Test with a hospitality business
    results = collect_news("McDonald's", days_back=90)

    # Print each article nicely
    for i, article in enumerate(results):
        print(f"Article {i+1}:")
        print(f"  Publisher : {article['publisher']}")
        print(f"  Title     : {article['title']}")
        print(f"  Date      : {article['timestamp']}")
        print(f"  Summary   : {article['body'][:100]}..." if article['body'] else "  Summary   : N/A")
        print(f"  URL       : {article['url']}")
        print()

    # Also save raw output to a JSON file so you can inspect it
    with open("news_results.json", "w") as f:
        json.dump(results, f, indent=2)
    print(f"\n Full results saved to news_results.json")