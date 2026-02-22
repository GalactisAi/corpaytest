"""
Corpay Newsroom Scraper
Fetches the latest items from the public Corpay corporate newsroom.
Uses limit=20 so newest posts (e.g. Feb 11 at 8:30 AM) are not cut off by featured items.
Source: `https://www.corpay.com/corporate-newsroom?limit=20&years=&categories=&search=`
"""
from typing import List, Dict
import json
import re
import time
import os

import httpx
from bs4 import BeautifulSoup

CORPAY_NEWSROOM_URL = "https://www.corpay.com/corporate-newsroom?limit=20&years=&categories=&search="
CORPAY_RESOURCES_NEWSROOM_URL = "https://www.corpay.com/resources/newsroom?page=2"
CORPAY_CUSTOMER_STORIES_BASE = "https://www.corpay.com/resources/customer-stories"
DEBUG_LOG_PATH = (os.getenv("APP_DEBUG_LOG_PATH") or "").strip()
# Agent debug log (NDJSON) for this session
_AGENT_LOG_PATH = (os.getenv("APP_DEBUG_LOG_PATH") or "").strip()

def _agent_log(location: str, message: str, data: dict, hypothesis_id: str = ""):
  # region agent log
  try:
    import time as _t
    if not _AGENT_LOG_PATH:
      return
    _dir = os.path.dirname(_AGENT_LOG_PATH)
    if _dir:
      os.makedirs(_dir, exist_ok=True)
    payload = {"id": f"log_{int(_t.time()*1000)}", "timestamp": int(_t.time()*1000), "location": location, "message": message, "data": data}
    if hypothesis_id:
      payload["hypothesisId"] = hypothesis_id
    with open(_AGENT_LOG_PATH, "a", encoding="utf-8") as f:
      f.write(json.dumps(payload, ensure_ascii=False) + "\n")
  except Exception:
    pass
  # endregion agent log

# Junk text that must not be shown as a date (e.g. UI labels from the page)
_DATE_JUNK = frozenset({"is showing", "showing", "show", "view", "read more", "—", "-", ""})

# Only accept date strings that look like real dates (4-digit year + month or numeric date)
_VALID_DATE_PATTERN = re.compile(
    r"(?:19|20)\d{2}"  # year 19xx or 20xx
    r"|"
    r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{1,2},?\s+(?:19|20)\d{2}"
    r"|"
    r"\d{1,2}[\s/\-]\d{1,2}[\s/\-](?:19|20)\d{2}"
)

# Faded date on Corpay listing; "at" optional so "Feb 11, 2026 8:30 AM" or "Feb 11, 2026 at 8:30 AM" both match
_FADED_DATE_TIME_RE = re.compile(
    r"(January|February|March|April|May|June|July|August|September|October|November|December|Jan\.?|Feb\.?|Mar\.?|Apr\.?|Jun\.?|Jul\.?|Aug\.?|Sep\.?|Oct\.?|Nov\.?|Dec\.?)\s+\d{1,2},?\s+\d{4}(?:(?:\s*at\s*)?\d{1,2}:\d{2}\s*[AP]M)?",
    re.I,
)


def _is_valid_date_text(s: str) -> bool:
    """Return True if s looks like a real date or is empty. Do not discard items with parsing issues. Allow time strings like 'February 11, 2026 at 8:30 AM' (up to 120 chars)."""
    if not s or s.strip() == "":
        return True
    t = s.strip().lower()
    if t in _DATE_JUNK:
      # region agent log
      _agent_log("newsroom_scraper.py:_is_valid_date_text", "REJECTED DATE (junk)", {"date_text": s, "len": len(s)}, "H1")
      # endregion agent log
      return False
    # Accept Corpay listing format first (e.g. "February 11, 2026 at 8:30 AM")
    if _FADED_DATE_TIME_RE.search(s):
        return True
    if len(t) > 120:
      # region agent log
      _agent_log("newsroom_scraper.py:_is_valid_date_text", "REJECTED DATE (length)", {"date_text": s, "len": len(t), "limit": 120}, "H1")
      # endregion agent log
      return False
    if not _VALID_DATE_PATTERN.search(s):
      # region agent log
      _agent_log("newsroom_scraper.py:_is_valid_date_text", "REJECTED DATE (regex)", {"date_text": s, "len": len(s)}, "H1")
      # endregion agent log
      return False
    return True


def _date_from_url(url: str) -> str:
    """Extract a display date from URL path (e.g. /2025/01/15/ or -2025-01-15-). Returns '' if none."""
    if not url:
        return ""
    m = re.search(r"/(20\d{2})[-/](\d{1,2})[-/](\d{1,2})(?:/|$|-|\s)", url)
    if not m:
        m = re.search(r"(20\d{2})[-/](\d{1,2})[-/](\d{1,2})(?:/|$|-|\s)", url)
    if m:
        from datetime import datetime
        try:
            y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
            if 1 <= mo <= 12 and 1 <= d <= 31:
                return datetime(y, mo, d).strftime("%b %d, %Y")
        except (ValueError, TypeError):
            pass
    return ""


async def _fetch_date_from_article_page(client: httpx.AsyncClient, article_url: str) -> str:
    """
    Fetch a single article page and extract the published date from meta tags or body.
    Used when the newsroom listing page doesn't include a date for that item.
    """
    date_text = ""
    try:
        response = await client.get(article_url, headers=CUSTOMER_STORIES_HEADERS)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        # Meta tags: og:published_time, article:published_time
        for meta in soup.find_all("meta", attrs={"property": True}):
            prop = (meta.get("property") or "").strip().lower()
            content = (meta.get("content") or "").strip()
            if prop in ("article:published_time", "og:published_time") and content:
                if re.match(r"^\d{4}-\d{2}-\d{2}", content):
                    try:
                        from datetime import datetime
                        # ISO date part YYYY-MM-DD
                        y, mo, d = content[:10].split("-")
                        y, mo, d = int(y), int(mo), int(d)
                        if 1 <= mo <= 12 and 1 <= d <= 31:
                            date_text = datetime(y, mo, d).strftime("%b %d, %Y")
                    except (ValueError, TypeError):
                        date_text = content[:10]
                if date_text:
                    break
        if not date_text:
            # First date-like pattern in main content
            main = soup.find("main") or soup.find("article") or soup
            text = main.get_text(separator=" ", strip=True) or ""
            m = re.search(
                r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{1,2},?\s+\d{4}|\d{1,2}[\s/\-]\d{1,2}[\s/\-]\d{2,4}",
                text,
                re.I,
            )
            if m and _is_valid_date_text(m.group(0).strip()):
                date_text = m.group(0).strip()
    except Exception:
        pass
    return date_text


# Browser-like headers so Corpay returns full HTML (not bot/minimal)
CUSTOMER_STORIES_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


def _debug_log(run_id: str, hypothesis_id: str, location: str, message: str, data: Dict) -> None:
  # region agent log
  try:
    if not DEBUG_LOG_PATH:
      return
    with open(DEBUG_LOG_PATH, "a", encoding="utf-8") as f:
      f.write(json.dumps({
        "sessionId": "debug-session",
        "runId": run_id,
        "hypothesisId": hypothesis_id,
        "location": location,
        "message": message,
        "data": data,
        "timestamp": int(time.time() * 1000),
      }) + "\n")
  except Exception:
    # Logging must never break main logic
    pass
  # endregion agent log


async def fetch_corpay_newsroom(limit: int = 12) -> List[Dict]:
  """
  Fetch and parse the latest newsroom items from corpay.com.
  Uses official page structure: div.corporate-newsroom_article-container with
  span.corporate-newsroom_date, span.corporate-newsroom_tag, and article link.
  Returns items sorted by publish datetime (newest first).
  """
  from datetime import datetime as _dt

  items: List[Dict] = []
  seen_urls: set = set()
  try:
    async with httpx.AsyncClient(timeout=httpx.Timeout(5.0, read=10.0)) as client:
      response = await client.get(CORPAY_NEWSROOM_URL, headers=CUSTOMER_STORIES_HEADERS)
      response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")

    article_containers = soup.find_all("div", class_=re.compile("corporate-newsroom_article-container"))
    for container in article_containers:
      # Robust date: prefer p.corporate-newsroom_date-time > span.corporate-newsroom_date, else span with class, else span containing "2026"
      date_span = None
      date_p = container.find("p", class_=re.compile("corporate-newsroom_date-time"))
      if date_p:
        date_span = date_p.find("span", class_=re.compile("corporate-newsroom_date"))
      if not date_span:
        date_span = container.find("span", class_=re.compile("corporate-newsroom_date"))
      if not date_span:
        for span in container.find_all("span"):
          if "2026" in (span.get_text() or ""):
            date_span = span
            break
      tag_span = container.find("span", class_=re.compile("corporate-newsroom_tag"))
      link = container.find("a", href=re.compile(r"/corporate-newsroom/"))
      if not link or not link.get("href"):
        continue
      href = (link.get("href") or "").strip()
      full_url = href if href.startswith("http") else f"https://www.corpay.com{href}"
      if full_url in seen_urls:
        continue
      seen_urls.add(full_url)

      date_text = " ".join(date_span.stripped_strings) if date_span else ""
      date_text = re.sub(r"\s*at\s*", " at ", date_text)
      date_text = re.sub(r"\s+", " ", date_text).strip()
      category = (tag_span.get_text(strip=True) if tag_span else "").strip() or "Press Releases"
      title = (link.get_text(separator=" ", strip=True) if link else "").strip()
      if not title:
        continue

      parsed_datetime = None
      if date_text:
        print(f"DEBUG: Found Raw Date: '{date_text}'")
        try:
          parsed_datetime = _dt.strptime(date_text, "%B %d, %Y at %I:%M %p")
        except Exception:
          try:
            parsed_datetime = _dt.strptime(date_text, "%B %d, %Y")
          except Exception:
            try:
              parsed_datetime = _dt.strptime(date_text, "%b %d, %Y")
            except Exception:
              parsed_datetime = None

      items.append({
        "title": title,
        "url": full_url,
        "date": date_text,
        "datetime": parsed_datetime,
        "category": category,
        "excerpt": "",
      })

  except Exception:
    return []

  items = sorted(items, key=lambda x: x.get("datetime") or _dt.min, reverse=True)
  return items[:limit]


async def fetch_corpay_resources_newsroom(limit: int = 4) -> List[Dict]:
  """
  Fetch and parse the latest items from Corpay Resources » Newsroom.

  Source: https://www.corpay.com/resources/newsroom?page=2
  We only return lightweight text content (no images) for the Resources box.
  """
  items: List[Dict] = []

  try:
    _debug_log("resources-pre", "R1", "newsroom_scraper.py:fetch_corpay_resources_newsroom:start",
               "Starting fetch_corpay_resources_newsroom", {"limit": limit, "url": CORPAY_RESOURCES_NEWSROOM_URL})

    # 5s connect timeout (fail fast if unreachable), 10s read timeout
    async with httpx.AsyncClient(timeout=httpx.Timeout(5.0, read=10.0)) as client:
      response = await client.get(CORPAY_RESOURCES_NEWSROOM_URL)
      _debug_log("resources-pre", "R2", "newsroom_scraper.py:fetch_corpay_resources_newsroom:response",
                 "Fetched resources HTML", {"status": response.status_code})
      response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")

    # Articles are listed under the main content area; titles are in <h2> tags.
    # We pair each title with its nearest "Read more" link and optional
    # category / short excerpt when available.
    main = soup.find("main") or soup
    h2_nodes = list(main.find_all("h2"))
    _debug_log("resources-pre", "R3", "newsroom_scraper.py:fetch_corpay_resources_newsroom:parsed",
               "Parsed resources HTML", {"h2Count": len(h2_nodes)})
    for h2 in h2_nodes:
      title = (h2.get_text(strip=True) or "").strip()
      if not title:
        continue

      # Find the first sibling link that points to a newsroom article.
      link = h2.find_next("a", href=True)
      href = link["href"] if link else ""
      if not href:
        continue

      container = h2.find_parent("article") or h2.parent
      category = ""
      excerpt = ""
      date_text = ""

      if container:
        # Date: <time> text, datetime attribute, or date-like class/text.
        time_el = container.find("time")
        if time_el:
          date_text = time_el.get_text(strip=True) or ""
          if not date_text and time_el.get("datetime"):
            try:
              from datetime import datetime
              dt = datetime.fromisoformat(time_el["datetime"].replace("Z", "+00:00")[:10])
              date_text = dt.strftime("%b %d, %Y")
            except Exception:
              date_text = time_el["datetime"][:10]
        if not date_text:
          for el in container.find_all(class_=re.compile(r"date|time|meta", re.I)):
            t = (el.get_text(strip=True) or "").strip()
            if t and re.search(r"\d{1,2}[\s/\-]\d{1,2}[\s/\-]\d{2,4}|\d{4}[\s/\-]\d{1,2}[\s/\-]\d{1,2}|(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{1,2},?\s+\d{4}", t):
              date_text = t
              break
        if not date_text:
          full_text = container.get_text(separator=" ", strip=True) or ""
          m = re.search(r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{1,2},?\s+\d{4}|\d{1,2}[\s/\-]\d{1,2}[\s/\-]\d{2,4}", full_text)
          if m:
            date_text = m.group(0).strip()
        if not date_text:
          sibling = h2.find_next_sibling()
          next_h2 = h2.find_next("h2")
          while sibling and sibling != next_h2:
            time_el = sibling.find("time") if hasattr(sibling, "find") else None
            if time_el:
              date_text = time_el.get_text(strip=True) or ""
              if not date_text and time_el.get("datetime"):
                try:
                  from datetime import datetime
                  dt = datetime.fromisoformat(time_el["datetime"].replace("Z", "+00:00")[:10])
                  date_text = dt.strftime("%b %d, %Y")
                except Exception:
                  date_text = time_el["datetime"][:10]
              if date_text:
                break
            if hasattr(sibling, "get_text"):
              t = sibling.get_text(separator=" ", strip=True) or ""
              m = re.search(r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{1,2},?\s+\d{4}|\d{1,2}[\s/\-]\d{1,2}[\s/\-]\d{2,4}|\d{1,2}\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{4}", t)
              if m:
                date_text = m.group(0).strip()
                break
            sibling = sibling.find_next_sibling() if hasattr(sibling, "find_next_sibling") else None

        # Category text like "Payments Automation" is often in a nearby element.
        cat_el = container.find(
          ["span", "a"],
          string=lambda s: isinstance(s, str) and len(s.strip()) > 0
        )
        if cat_el:
          category = cat_el.get_text(strip=True)

        # Excerpt paragraph, if present.
        para = container.find("p")
        if para:
          excerpt = para.get_text(strip=True)

      if not _is_valid_date_text(date_text):
        date_text = ""
      # Ensure every article has an absolute URL (relative e.g. /resources/... -> https://www.corpay.com/...)
      full_url = href if href.startswith("http") else f"https://www.corpay.com{href}"
      if not date_text:
        date_text = _date_from_url(full_url)

      items.append(
        {
          "title": title,
          "url": full_url,
          "date": date_text,
          "category": category,
          "excerpt": excerpt,
        }
      )

      if len(items) >= limit:
        break

  except Exception as e:
    _debug_log("resources-pre", "R4", "newsroom_scraper.py:fetch_corpay_resources_newsroom:exception",
               "Exception in fetch_corpay_resources_newsroom", {"error": str(e)})
    return []

  _debug_log("resources-pre", "R5", "newsroom_scraper.py:fetch_corpay_resources_newsroom:end",
             "Returning resources items", {"returnedCount": len(items)})

  # Keep original page order (already newest-first on corpay.com)
  return items


async def fetch_corpay_customer_stories(limit: int = 12, max_pages: int = 3) -> List[Dict]:
  """
  Fetch and parse case studies from Corpay Customer Stories.

  Source: https://www.corpay.com/resources/customer-stories
  Fetches the first page and optionally more pages (page=1, page=2, ...) to include
  every new case study posted there. Returns title, url, excerpt, category (tags).
  """
  items: List[Dict] = []
  seen_urls: set = set()

  try:
    async with httpx.AsyncClient(timeout=httpx.Timeout(5.0, read=15.0)) as client:
      for page_num in range(1, max_pages + 1):
        url = CORPAY_CUSTOMER_STORIES_BASE if page_num == 1 else f"{CORPAY_CUSTOMER_STORIES_BASE}?page={page_num}"
        try:
          response = await client.get(url, headers=CUSTOMER_STORIES_HEADERS)
          response.raise_for_status()
        except Exception:
          break

        html = response.text
        soup = BeautifulSoup(html, "html.parser")

        # Try Next.js __NEXT_DATA__ first (page data may be embedded)
        try:
          script = soup.find("script", id="__NEXT_DATA__")
          if script and script.string:
            data = json.loads(script.string)
            props = (data.get("props") or {}).get("pageProps") or {}
            raw_list = props.get("resources") or props.get("items") or props.get("cards") or props.get("posts") or []
            if isinstance(raw_list, list):
              base = "https://www.corpay.com"
              for entry in raw_list:
                if not isinstance(entry, dict):
                  continue
                u = entry.get("url") or entry.get("link")
                if not u and entry.get("slug"):
                  slug = str(entry["slug"]).strip()
                  u = (base + slug) if slug.startswith("/") else f"{base}/resources/customer-stories/{slug}"
                if not u or "customer-stories" not in str(u):
                  continue
                if not u.startswith("http"):
                  u = base + (u if u.startswith("/") else "/resources/customer-stories/" + u)
                if u in seen_urls:
                  continue
                seen_urls.add(u)
                tit = (entry.get("title") or entry.get("name") or entry.get("headline") or "Case Study").strip()
                ex = (entry.get("excerpt") or entry.get("description") or entry.get("summary") or "").strip() or None
                tags = entry.get("tags") or entry.get("categories") or entry.get("category")
                cat = tags[0] if isinstance(tags, list) and tags and isinstance(tags[0], str) else (tags if isinstance(tags, str) else None)
                items.append({"title": tit, "url": u, "excerpt": ex[:400] if ex else None, "category": cat})
                if len(items) >= limit:
                  break
          if len(items) >= limit:
            break
        except Exception:
          pass

        # Parse HTML: search body for links to specific case study pages
        body = soup.find("body") or soup
        for a in body.find_all("a", href=True):
          if len(items) >= limit:
            break
          href = (a.get("href") or "").strip().split("?")[0]
          if not href or "/customer-stories/" not in href:
            continue
          full_url = href if href.startswith("http") else f"https://www.corpay.com{href}"
          if full_url.rstrip("/").endswith("customer-stories"):
            continue
          if full_url in seen_urls:
            continue
          seen_urls.add(full_url)

          title = (a.get_text(strip=True) or "").strip()
          if title.endswith(" - Resource"):
            title = title[:-11].strip()
          if not title or len(title) < 2:
            parent = a.find_parent(["h1", "h2", "h3", "h4", "h5", "h6"])
            title = (parent.get_text(strip=True) or "").strip() if parent else "Case Study"
          if not title:
            title = "Case Study"
          if len(title) > 120:
            title = title[:117] + "..."

          excerpt = ""
          category = ""
          container = (
            a.find_parent("article")
            or a.find_parent("div", class_=re.compile(r"card|item|story|resource|grid|teaser", re.I))
            or a.parent
          )
          if container:
            for tag in ("h6", "h2", "h3", "p"):
              for node in container.find_all(tag):
                t = (node.get_text(strip=True) or "").strip()
                if t and t != title and len(t) > 15:
                  excerpt = t[:400]
                  break
              if excerpt:
                break
            if not excerpt:
              for node in container.find_all(["p", "div"]):
                t = (node.get_text(strip=True) or "").strip()
                if t and t != title and 20 <= len(t) <= 500:
                  excerpt = t[:400]
                  break
            for node in container.find_all(["span", "a", "p"]):
              t = (node.get_text(strip=True) or "").strip()
              if 2 <= len(t) <= 50 and t != title and "customer-stories" not in (node.get("href") or ""):
                if re.match(r"^[A-Za-z][A-Za-z\s&\-]+$", t):
                  category = t
                  break

          items.append({
            "title": title,
            "url": full_url,
            "excerpt": excerpt or None,
            "category": category or None,
          })
          if len(items) >= limit:
            break

        if len(items) >= limit:
          break

  except Exception:
    return items

  return items[:limit]
