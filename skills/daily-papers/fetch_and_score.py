#!/usr/bin/env python3
"""
fetch_and_score.py — Phase 1+2: Fetch, score, merge, dedup, select top 30.

Replaces the two LLM Task Agents with pure Python. Zero token cost.

Usage:
    python3 fetch_and_score.py > /tmp/daily_papers_top30.json
    python3 fetch_and_score.py --date 2026-02-25 > /tmp/daily_papers_top30.json
    python3 fetch_and_score.py --days 7 > /tmp/daily_papers_top30.json

Stderr: progress logs.  Stdout: JSON array of top papers (30 * days).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from pathlib import Path
from urllib.error import URLError
from urllib.parse import quote_plus
from urllib.request import Request, urlopen

_SHARED_DIR = Path(__file__).resolve().parent.parent / "_shared"
if str(_SHARED_DIR) not in sys.path:
    sys.path.insert(0, str(_SHARED_DIR))

from user_config import daily_papers_config, daily_papers_dir

# ── Configuration ──────────────────────────────────────────────────────────

_CONFIG = daily_papers_config()

KEYWORDS = _CONFIG["keywords"]
NEGATIVE_KEYWORDS = _CONFIG["negative_keywords"]
DOMAIN_BOOST_KEYWORDS = _CONFIG["domain_boost_keywords"]
ARXIV_CATEGORIES = _CONFIG["arxiv_categories"]
MIN_SCORE = _CONFIG["min_score"]
TOP_N = _CONFIG["top_n"]
CONFERENCE_VENUES = _CONFIG.get("conference_venues", [])

DAILYPAPERS_DIR = daily_papers_dir()
HISTORY_PATH = DAILYPAPERS_DIR / ".history.json"

ATOM_NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "arxiv": "http://arxiv.org/schemas/atom",
}

# ── Scoring ────────────────────────────────────────────────────────────────


def score_paper(paper: dict, is_trending: bool = False) -> int:
    text = (paper["title"] + " " + paper["abstract"]).lower()
    title_lower = paper["title"].lower()

    # 1. Negative keywords → instant reject
    for neg in NEGATIVE_KEYWORDS:
        if neg in text:
            return -999

    score = 0

    # 2. Positive keywords
    keyword_hits = 0
    for kw in KEYWORDS:
        if kw in title_lower:
            score += 3
            keyword_hits += 1
        elif kw in text:
            score += 1
            keyword_hits += 1

    # 3. Domain boost
    domain_hits = sum(1 for kw in DOMAIN_BOOST_KEYWORDS if kw in text)
    if domain_hits >= 2:
        score += 2
    elif domain_hits == 1:
        score += 1

    # 4. Trending boost (HF sources only)
    #    GATE: only apply if paper has at least 1 keyword or domain match,
    #    to prevent irrelevant but popular papers from flooding the list
    has_relevance = keyword_hits > 0 or domain_hits > 0
    if is_trending:
        upvotes = paper.get("hf_upvotes", 0) or 0
        if has_relevance:
            # Relevant + trending → full boost
            if upvotes >= 10:
                score += 3
            elif upvotes >= 5:
                score += 2
            elif upvotes >= 2:
                score += 1
        else:
            # No relevance → minimal boost (only very popular papers get a chance)
            if upvotes >= 20:
                score += 1

    return score


# ── SSL context (fixes macOS Python cert issues) ─────────────────────────


def _build_ssl_context():
    import ssl
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        return ctx

_SSL_CTX = None


# ── Fetchers ───────────────────────────────────────────────────────────────


def fetch_url(url: str, timeout: int = 30, retries: int = 2) -> str:
    from urllib.error import HTTPError
    ctx = _SSL_CTX
    if ctx is None:
        globals()["_SSL_CTX"] = _build_ssl_context()
        ctx = _SSL_CTX
    for attempt in range(1, retries + 1):
        try:
            req = Request(url, headers={"User-Agent": "daily-papers-bot/1.0"})
            with urlopen(req, timeout=timeout, context=ctx) as resp:
                return resp.read().decode("utf-8")
        except HTTPError as e:
            if e.code == 429:
                wait = int(e.headers.get("Retry-After", 5))
                print(f"  [429] Rate limited, waiting {wait}s (attempt {attempt})...", file=sys.stderr)
                time.sleep(wait)
                continue
            print(f"  [WARN] fetch failed {url}: {e}", file=sys.stderr)
            return ""
        except Exception as e:
            print(f"  [WARN] fetch failed {url}: {e}", file=sys.stderr)
            return ""
    return ""


def _parse_hf_item(item: dict, source: str) -> tuple[str, dict] | None:
    """Parse a single HF API item into (arxiv_id, paper_dict). Returns None on skip."""
    p = item.get("paper", {})
    arxiv_id = p.get("id", "")
    if not arxiv_id:
        return None

    upvotes = p.get("upvotes", 0)

    # Authors
    authors_raw = p.get("authors", [])
    if isinstance(authors_raw, list):
        names = []
        for a in authors_raw:
            if isinstance(a, dict):
                names.append(a.get("name", ""))
            elif isinstance(a, str):
                names.append(a)
        authors = ", ".join(n for n in names if n)
    else:
        authors = str(authors_raw)

    paper = {
        "title": p.get("title", ""),
        "authors": authors,
        "affiliations": "",
        "abstract": p.get("summary", ""),
        "url": f"https://arxiv.org/abs/{arxiv_id}",
        "pdf": f"https://arxiv.org/pdf/{arxiv_id}",
        "date": (p.get("publishedAt") or "")[:10],
        "score": 0,
        "category": "",
        "source": source,
        "hf_upvotes": upvotes,
    }

    is_trending = source == "hf-trending"
    paper["score"] = score_paper(paper, is_trending=is_trending)

    if paper["score"] < 0:
        return None

    return arxiv_id, paper


def fetch_hf_papers(start_date=None, end_date=None) -> list[dict]:
    papers = {}  # arxiv_id → paper

    # ── hf-daily: loop each day in range ──
    if start_date and end_date:
        d = start_date
        while d <= end_date:
            date_str = d.isoformat()
            endpoint = f"https://huggingface.co/api/daily_papers?date={date_str}&limit=100"
            print(f"  Fetching hf-daily {date_str}...", file=sys.stderr)
            raw = fetch_url(endpoint)
            if raw:
                try:
                    items = json.loads(raw)
                except json.JSONDecodeError:
                    items = []
                    print(f"  [WARN] bad JSON from hf-daily {date_str}", file=sys.stderr)
                for item in items:
                    result = _parse_hf_item(item, "hf-daily")
                    if result:
                        arxiv_id, paper = result
                        if arxiv_id not in papers or paper["score"] > papers[arxiv_id]["score"]:
                            papers[arxiv_id] = paper
            d += timedelta(days=1)
    else:
        # Legacy single-call (days=1 default)
        endpoint = "https://huggingface.co/api/daily_papers?limit=50"
        print(f"  Fetching hf-daily...", file=sys.stderr)
        raw = fetch_url(endpoint)
        if raw:
            try:
                items = json.loads(raw)
            except json.JSONDecodeError:
                items = []
                print(f"  [WARN] bad JSON from hf-daily", file=sys.stderr)
            for item in items:
                result = _parse_hf_item(item, "hf-daily")
                if result:
                    arxiv_id, paper = result
                    if arxiv_id not in papers or paper["score"] > papers[arxiv_id]["score"]:
                        papers[arxiv_id] = paper

    # ── hf-trending: always single call (not date-dependent) ──
    endpoint = "https://huggingface.co/api/daily_papers?sort=trending&limit=50"
    print(f"  Fetching hf-trending...", file=sys.stderr)
    raw = fetch_url(endpoint)
    if raw:
        try:
            items = json.loads(raw)
        except json.JSONDecodeError:
            items = []
            print(f"  [WARN] bad JSON from hf-trending", file=sys.stderr)
        for item in items:
            result = _parse_hf_item(item, "hf-trending")
            if result:
                arxiv_id, paper = result
                if arxiv_id not in papers or paper["score"] > papers[arxiv_id]["score"]:
                    papers[arxiv_id] = paper

    result = list(papers.values())
    print(f"  HF: {len(result)} papers after scoring", file=sys.stderr)
    return result


def fetch_arxiv_papers(start_date=None, end_date=None, days: int = 1) -> list[dict]:
    max_results = min(400 * days, 3000)
    cats = "+OR+".join(f"cat:{c}" for c in ARXIV_CATEGORIES)
    url = (
        f"https://export.arxiv.org/api/query?"
        f"search_query=({cats})"
        f"&sortBy=submittedDate&sortOrder=descending&max_results={max_results}"
    )

    timeout = max(60, 30 * days)
    print(f"  Fetching arXiv (max_results={max_results}, timeout={timeout}s)...", file=sys.stderr)
    xml_text = fetch_url(url, timeout=timeout)
    if not xml_text:
        return []

    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as e:
        print(f"  [WARN] arXiv XML parse error: {e}", file=sys.stderr)
        return []

    papers = []
    filtered_by_date = 0
    for entry in root.findall("atom:entry", ATOM_NS):
        title_el = entry.find("atom:title", ATOM_NS)
        summary_el = entry.find("atom:summary", ATOM_NS)
        published_el = entry.find("atom:published", ATOM_NS)
        id_el = entry.find("atom:id", ATOM_NS)

        if title_el is None or summary_el is None:
            continue

        title = " ".join(title_el.text.split())
        abstract = " ".join(summary_el.text.split())
        entry_url = id_el.text.strip() if id_el is not None else ""
        date = published_el.text[:10] if published_el is not None else ""
        arxiv_id = entry_url.split("/abs/")[-1] if "/abs/" in entry_url else ""

        # Date filter: only apply in multi-day mode (days > 1)
        # In single-day mode, arXiv batches span 2-3 days, so filtering would be too strict
        if days > 1 and start_date and end_date and date:
            try:
                pub_date = datetime.strptime(date, "%Y-%m-%d").date()
                if pub_date < start_date or pub_date > end_date:
                    filtered_by_date += 1
                    continue
            except ValueError:
                pass  # keep papers with unparseable dates

        author_els = entry.findall("atom:author", ATOM_NS)
        names = []
        affiliations = set()
        for a in author_els:
            name_el = a.find("atom:name", ATOM_NS)
            if name_el is not None and name_el.text:
                names.append(name_el.text.strip())
            for aff_el in a.findall("arxiv:affiliation", ATOM_NS):
                if aff_el.text and aff_el.text.strip():
                    affiliations.add(aff_el.text.strip())

        cat_el = entry.find("arxiv:primary_category", ATOM_NS)
        category = cat_el.get("term", "") if cat_el is not None else ""

        papers.append({
            "title": title,
            "authors": ", ".join(names),
            "affiliations": ", ".join(sorted(affiliations)) if affiliations else "",
            "abstract": abstract,
            "url": entry_url,
            "pdf": f"https://arxiv.org/pdf/{arxiv_id}" if arxiv_id else "",
            "date": date,
            "score": 0,
            "category": category,
            "source": "arxiv",
        })

    scored = []
    for p in papers:
        p["score"] = score_paper(p)
        if p["score"] >= 0:
            scored.append(p)

    print(
        f"  arXiv: {len(scored)} papers after scoring (from {len(papers)} parsed, {filtered_by_date} filtered by date)",
        file=sys.stderr,
    )
    return scored


# ── Conference papers from DBLP ───────────────────────────────────────────


def _dblp_fetch(url: str, timeout: int = 30) -> str:
    """Fetch URL with proper SSL context for DBLP (same as fetch_url)."""
    return fetch_url(url, timeout=timeout)


def _load_dblp_cache() -> list[dict] | None:
    """Return cached DBLP papers if cache is from today, else None."""
    cache_path = DAILYPAPERS_DIR / ".dblp_cache.json"
    if not cache_path.exists():
        return None
    try:
        data = json.loads(cache_path.read_text(encoding="utf-8"))
        if data.get("date") == datetime.now().date().isoformat():
            print("  DBLP: using today's cache", file=sys.stderr)
            return data.get("papers", [])
    except (json.JSONDecodeError, IOError):
        pass
    return None


def _save_dblp_cache(papers: list[dict]) -> None:
    cache_path = DAILYPAPERS_DIR / ".dblp_cache.json"
    try:
        cache_path.write_text(json.dumps(
            {"date": datetime.now().date().isoformat(), "papers": papers},
            ensure_ascii=False,
        ), encoding="utf-8")
    except IOError as e:
        print(f"  [WARN] failed to write DBLP cache: {e}", file=sys.stderr)


def _parse_dblp_hits(hits: list, dblp_key: str, vname: str,
                      seen_titles: set[str]) -> list[dict]:
    """Parse DBLP search hits into paper dicts."""
    papers = []
    for hit in hits:
        info = hit.get("info", {})

        if info.get("type", "") not in ("Conference and Workshop Papers", ""):
            continue

        dblp_url = info.get("url", "")
        if dblp_key not in dblp_url:
            continue

        title = info.get("title", "").rstrip(".")
        title_key = _normalize_title(title)
        if not title_key or title_key in seen_titles:
            continue
        seen_titles.add(title_key)

        authors_data = info.get("authors", {})
        author_list = authors_data.get("author", [])
        if isinstance(author_list, dict):
            author_list = [author_list]
        authors = ", ".join(
            a.get("text", "") if isinstance(a, dict) else str(a)
            for a in author_list
        )

        paper_url = info.get("ee", "")
        if isinstance(paper_url, list):
            paper_url = paper_url[0] if paper_url else ""
        if not paper_url:
            paper_url = dblp_url

        year = info.get("year", "")

        paper = {
            "title": title,
            "authors": authors,
            "affiliations": "",
            "abstract": "",
            "url": paper_url,
            "pdf": "",
            "date": f"{year}-01-01" if year else "",
            "score": 0,
            "category": "",
            "source": f"dblp-{vname}",
            "venue": vname,
        }

        base_score = score_paper(paper)
        paper["score"] = max(base_score, 0) + 5
        papers.append(paper)
    return papers


def fetch_conference_papers() -> list[dict]:
    """Fetch recent conference papers from DBLP for configured venues.

    Results are cached daily to avoid hammering DBLP's API.
    """
    cached = _load_dblp_cache()
    if cached is not None:
        return cached

    current_year = datetime.now().year
    years = [current_year]

    papers = []
    seen_titles: set[str] = set()
    consecutive_failures = 0

    for venue in CONFERENCE_VENUES:
        vname = venue["name"]
        dblp_key = venue["dblp_key"]

        if consecutive_failures >= 3:
            print(f"  DBLP: skipping remaining venues after {consecutive_failures} consecutive failures",
                  file=sys.stderr)
            break

        for year in years:
            query = quote_plus(f"{vname} {year}")
            url = (
                f"https://dblp.org/search/publ/api?"
                f"q={query}&h=300&format=json"
            )

            time.sleep(3.0)
            raw = _dblp_fetch(url, timeout=30)
            if not raw:
                consecutive_failures += 1
                continue

            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                consecutive_failures += 1
                continue

            consecutive_failures = 0
            hits = data.get("result", {}).get("hits", {}).get("hit", [])
            venue_papers = _parse_dblp_hits(hits, dblp_key, vname, seen_titles)
            papers.extend(venue_papers)

        count = sum(1 for p in papers if p["venue"] == vname)
        if count:
            print(f"  DBLP {vname}: {count} papers", file=sys.stderr)

    print(f"  DBLP total: {len(papers)} conference papers", file=sys.stderr)
    _save_dblp_cache(papers)
    return papers


# ── Merge & Dedup ──────────────────────────────────────────────────────────


def extract_arxiv_id(url: str) -> str:
    m = re.search(r"(\d{4}\.\d{4,5})", url)
    return m.group(1) if m else ""


def _normalize_title(title: str) -> str:
    return re.sub(r'[^a-z0-9\s]', '', title.lower()).strip()


def _paper_key(paper: dict) -> str:
    aid = extract_arxiv_id(paper.get("url", ""))
    if aid:
        return f"arxiv:{aid}"
    title = _normalize_title(paper.get("title", ""))
    return f"title:{title}" if title else ""


def load_history() -> list[dict]:
    if HISTORY_PATH.exists():
        try:
            return json.loads(HISTORY_PATH.read_text())
        except (json.JSONDecodeError, IOError):
            pass
    return []


def load_fallback_ids(days: int = 7) -> set[str]:
    ids: set[str] = set()
    today = datetime.now().date()
    for d in range(1, days + 1):
        fpath = DAILYPAPERS_DIR / f"{(today - timedelta(days=d)).isoformat()}-论文推荐.md"
        if fpath.exists():
            try:
                text = fpath.read_text()
                for m in re.finditer(r"arxiv\.org/abs/(\d{4}\.\d{4,5})", text):
                    ids.add(m.group(1))
            except IOError:
                pass
    return ids


def merge_and_dedup(
    hf_papers: list[dict],
    arxiv_papers: list[dict],
    conference_papers: list[dict],
    target_date,
    days: int = 1,
    top_n: int = TOP_N,
) -> list[dict]:
    is_weekend = target_date.weekday() >= 5

    # ── merge by paper key (arXiv ID or title), keep higher score ──
    by_id: dict[str, dict] = {}
    for p in hf_papers + arxiv_papers + conference_papers:
        key = _paper_key(p)
        if not key:
            continue
        if key not in by_id or p["score"] > by_id[key]["score"]:
            by_id[key] = p

    # ── title-based cross-source dedup (arXiv + DBLP overlap) ──
    title_index: dict[str, list[str]] = {}
    for key in list(by_id.keys()):
        norm = _normalize_title(by_id[key].get("title", ""))
        if norm:
            title_index.setdefault(norm, []).append(key)
    for norm, keys in title_index.items():
        if len(keys) > 1:
            best = max(keys, key=lambda k: (k.startswith("arxiv:"), by_id[k]["score"]))
            for k in keys:
                if k != best:
                    venue = by_id[k].get("venue", "")
                    if venue and not by_id[best].get("venue"):
                        by_id[best]["venue"] = venue
                    by_id[best]["score"] = max(by_id[best]["score"], by_id[k]["score"])
                    del by_id[k]

    print(f"  Merged: {len(by_id)} unique papers", file=sys.stderr)

    if days > 1:
        # ── multi-day mode: skip history dedup ──
        # User explicitly wants to see all N days, don't filter out previously recommended
        print(f"  Multi-day mode (days={days}): skipping history dedup", file=sys.stderr)
        candidates = [p for p in by_id.values() if p["score"] >= MIN_SCORE]
        candidates.sort(key=lambda x: x["score"], reverse=True)
        top = candidates[:top_n]
        print(f"  Final: {len(top)} papers (top_n={top_n})", file=sys.stderr)
        return top

    # ── single-day mode: history dedup as before ──
    history = load_history()
    history_ids: dict[str, str] = {}  # id → earliest date
    for h in history:
        hid, hdate = h.get("id", ""), h.get("date", "")
        if hid and hdate:
            if hid not in history_ids or hdate < history_ids[hid]:
                history_ids[hid] = hdate

    if len(history) < 10:
        for fid in load_fallback_ids():
            history_ids.setdefault(fid, "unknown")

    # ── cross-day dedup (arXiv papers only; conference papers bypass) ──
    deduped: dict[str, dict] = {}
    removed = 0
    for key, p in by_id.items():
        aid = key[6:] if key.startswith("arxiv:") else ""
        if aid and aid in history_ids:
            # Weekend: keep trending with upvotes >= 5
            if is_weekend and p.get("source") == "hf-trending" and (p.get("hf_upvotes") or 0) >= 5:
                p["is_re_recommend"] = True
                p["last_recommend_date"] = history_ids[aid]
                deduped[key] = p
            else:
                removed += 1
        else:
            deduped[key] = p

    # Mark any remaining that appear in history
    for key, p in deduped.items():
        aid = key[6:] if key.startswith("arxiv:") else ""
        if aid and aid in history_ids and not p.get("is_re_recommend"):
            p["is_re_recommend"] = True
            p["last_recommend_date"] = history_ids[aid]

    print(f"  After history dedup: {len(deduped)} (removed {removed})", file=sys.stderr)

    # ── filter + sort ──
    candidates = [p for p in deduped.values() if p["score"] >= MIN_SCORE]
    candidates.sort(key=lambda x: x["score"], reverse=True)

    # Back-fill from history if pool is thin
    if len(candidates) < 20 and removed > 0:
        backfill = []
        for key, p in by_id.items():
            if key not in deduped and p["score"] >= MIN_SCORE:
                aid = key[6:] if key.startswith("arxiv:") else ""
                p["is_re_recommend"] = True
                p["last_recommend_date"] = history_ids.get(aid, "unknown") if aid else "unknown"
                backfill.append(p)
        backfill.sort(key=lambda x: x["score"], reverse=True)
        needed = 20 - len(candidates)
        candidates.extend(backfill[:needed])
        if backfill[:needed]:
            print(f"  Back-filled {min(needed, len(backfill))} from history", file=sys.stderr)

    top = candidates[:top_n]
    print(f"  Final: {len(top)} papers", file=sys.stderr)
    return top


# ── Main ───────────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", help="Target date YYYY-MM-DD (default: today)")
    parser.add_argument("--days", type=int, default=1, help="Number of days to fetch (default: 1)")
    args = parser.parse_args()

    target_date = (
        datetime.strptime(args.date, "%Y-%m-%d").date()
        if args.date
        else datetime.now().date()
    )
    days = max(1, args.days)
    start_date = target_date - timedelta(days=days - 1)
    top_n = TOP_N * days

    is_weekend = target_date.weekday() >= 5
    print(
        f"[fetch_and_score] {target_date} ({'weekend' if is_weekend else 'weekday'})"
        + (f", days={days} [{start_date} ~ {target_date}], top_n={top_n}" if days > 1 else ""),
        file=sys.stderr,
    )

    hf_papers = fetch_hf_papers(start_date, target_date)
    arxiv_papers = fetch_arxiv_papers(start_date, target_date, days)
    conf_papers = fetch_conference_papers() if CONFERENCE_VENUES else []
    top = merge_and_dedup(hf_papers, arxiv_papers, conf_papers, target_date, days=days, top_n=top_n)

    # Output to stdout (UTF-8 encoded for Windows compatibility)
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    json.dump(top, sys.stdout, ensure_ascii=False, indent=2)
    print(file=sys.stdout)  # trailing newline


if __name__ == "__main__":
    main()
