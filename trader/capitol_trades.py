"""Capitol Trades Data — Track US politician stock trades.

Capitol Trades is JS-rendered (Next.js), so direct scraping is unreliable.
This module uses multiple strategies:
1. Parse Next.js RSC payload from the HTML
2. Fetch the Senate/House disclosure RSS feeds directly
3. Fallback to raw HTML text extraction for LLM analysis
"""
import json
import re
import requests
import xml.etree.ElementTree as ET
from datetime import datetime


HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
}

# Senate financial disclosure RSS
SENATE_DISCLOSURES = "https://efdsearch.senate.gov/search/report/data/"
# House financial disclosure
HOUSE_DISCLOSURES = "https://disclosures-clerk.house.gov/FinancialDisclosure"


def get_recent_trades():
    """Get recent politician trades from Capitol Trades via RSC payload."""
    try:
        r = requests.get(
            "https://www.capitoltrades.com/trades",
            headers=HEADERS, timeout=15,
        )
        r.raise_for_status()
        return _parse_nextjs_payload(r.text, "trades")
    except Exception as e:
        return {"error": str(e)}


def get_top_traders():
    """Get most active politicians from Capitol Trades."""
    try:
        r = requests.get(
            "https://www.capitoltrades.com/politicians",
            headers=HEADERS, timeout=15,
        )
        r.raise_for_status()
        return _parse_nextjs_payload(r.text, "politicians")
    except Exception as e:
        return {"error": str(e)}


def get_politician_trades(slug):
    """Get trades for a specific politician."""
    try:
        r = requests.get(
            f"https://www.capitoltrades.com/politicians/{slug}/trades",
            headers=HEADERS, timeout=15,
        )
        r.raise_for_status()
        return _parse_nextjs_payload(r.text, "trades")
    except Exception as e:
        return {"error": str(e)}


def _parse_nextjs_payload(html, context="trades"):
    """Extract data from Next.js React Server Component payloads."""
    # Next.js embeds data in script tags with self.__next_f.push format
    chunks = re.findall(r'self\.__next_f\.push\(\[1,"(.*?)"\]\)', html, re.DOTALL)

    # Combine all chunks
    raw_data = "".join(chunks)
    # Unescape
    raw_data = raw_data.replace('\\"', '"').replace("\\n", "\n").replace("\\\\", "\\")

    # Extract structured data - look for trade/politician patterns
    results = []

    if context == "trades":
        # Look for trade entries - ticker symbols, buy/sell, amounts
        # Pattern: stock tickers near buy/sell words near dollar amounts
        trade_blocks = re.findall(
            r'([A-Z]{1,5}).*?(buy|sell|purchase|sale).*?\$?([\d,]+(?:\.\d+)?)',
            raw_data, re.IGNORECASE
        )
        seen = set()
        for symbol, action, amount in trade_blocks:
            if symbol in ("USD", "ETF", "LLC", "INC", "THE", "AND", "FOR", "RSS"):
                continue
            key = f"{symbol}-{action}-{amount}"
            if key not in seen:
                seen.add(key)
                results.append({
                    "symbol": symbol,
                    "action": "buy" if action.lower() in ("buy", "purchase") else "sell",
                    "amount": amount.replace(",", ""),
                })

    elif context == "politicians":
        # Look for politician name patterns
        name_patterns = re.findall(
            r'((?:Senator|Rep\.|Representative)\s+[A-Z][a-z]+\s+[A-Z][a-z]+)',
            raw_data
        )
        for name in list(set(name_patterns))[:20]:
            slug = name.split()[-1].lower()
            results.append({"name": name, "slug": slug})

    # If structured parsing found data, return it
    if results:
        return results

    # Fallback: return cleaned text for LLM to analyze
    clean = re.sub(r'<[^>]+>', ' ', html)
    clean = re.sub(r'\s+', ' ', clean).strip()

    # Find relevant section
    for marker in ["trades", "recent", "disclosure"]:
        idx = clean.lower().find(marker)
        if idx >= 0:
            return {
                "raw_text": clean[max(0, idx-100):idx+3000],
                "note": "Structured parsing found limited data. Raw text for LLM analysis.",
                "source": "capitoltrades.com",
            }

    return {
        "raw_text": clean[500:3500],
        "note": "Could not parse structured data. Raw page text returned.",
        "source": "capitoltrades.com",
    }
