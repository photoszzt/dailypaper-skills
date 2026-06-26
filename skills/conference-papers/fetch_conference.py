#!/usr/bin/env python3
"""
fetch_conference.py — Fetch and categorize papers from a specific conference via DBLP.

Reuses scoring and DBLP parsing from daily-papers/fetch_and_score.py.

Usage:
    python3 fetch_conference.py --venue NSDI --year 2026
    python3 fetch_conference.py --venue SOSP           # defaults to current year
    python3 fetch_conference.py --venue NSDI --year 2026 --format markdown
    python3 fetch_conference.py --list-venues

Stderr: progress logs.  Stdout: JSON or markdown output.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import quote_plus

_SHARED_DIR = Path(__file__).resolve().parent.parent / "_shared"
_DAILY_DIR = Path(__file__).resolve().parent.parent / "daily-papers"
for p in [str(_SHARED_DIR), str(_DAILY_DIR)]:
    if p not in sys.path:
        sys.path.insert(0, p)

from user_config import daily_papers_config
from fetch_and_score import (
    score_paper,
    fetch_url,
    _normalize_title,
)

KNOWN_VENUES = {
    "ASPLOS":  {"dblp_key": "conf/asplos",  "org": "ACM",      "query": "ASPLOS"},
    "HPCA":    {"dblp_key": "conf/hpca",    "org": "IEEE",     "query": "HPCA"},
    "HotNets": {"dblp_key": "conf/hotnets", "org": "ACM",      "query": "HotNets"},
    "HotOS":   {"dblp_key": "conf/hotos",   "org": "ACM",      "query": "HotOS"},
    "FAST":    {"dblp_key": "conf/fast",     "org": "USENIX",  "query": "USENIX FAST"},
    "NSDI":    {"dblp_key": "conf/nsdi",     "org": "USENIX",  "query": "NSDI"},
    "SIGCOMM": {"dblp_key": "conf/sigcomm",  "org": "ACM",      "query": "SIGCOMM"},
    "EuroSys": {"dblp_key": "conf/eurosys",  "org": "ACM",      "query": "EuroSys"},
    "SOSP":    {"dblp_key": "conf/sosp",     "org": "ACM",      "query": "SOSP"},
    "OSDI":    {"dblp_key": "conf/osdi",     "org": "USENIX",  "query": "OSDI"},
    "MLSys":   {"dblp_key": "conf/mlsys",    "org": "MLSys",    "query": "MLSys"},
    "ATC":     {"dblp_key": "conf/usenix",   "org": "USENIX",  "query": "USENIX Annual Technical"},
    "SIGMOD":  {"dblp_key": "conf/sigmod",   "org": "ACM",      "query": "SIGMOD"},
    "VLDB":    {"dblp_key": "conf/vldb",     "org": "VLDB",     "query": "VLDB"},
    "ISCA":    {"dblp_key": "conf/isca",     "org": "ACM/IEEE", "query": "ISCA"},
    "MICRO":   {"dblp_key": "conf/micro",    "org": "ACM/IEEE", "query": "MICRO"},
    "SC":      {"dblp_key": "conf/sc",       "org": "ACM/IEEE", "query": "Supercomputing"},
    "INFOCOM": {"dblp_key": "conf/infocom",  "org": "IEEE",     "query": "INFOCOM"},
    "IMC":     {"dblp_key": "conf/imc",      "org": "ACM",      "query": "Internet Measurement Conference"},
    "CoNEXT":  {"dblp_key": "conf/conext",   "org": "ACM",      "query": "CoNEXT"},
    "PLDI":    {"dblp_key": "conf/pldi",     "org": "ACM",      "query": "PLDI"},
    "PPoPP":   {"dblp_key": "conf/ppopp",    "org": "ACM",      "query": "PPoPP"},
    "SoCC":    {"dblp_key": "conf/cloud",    "org": "ACM",      "query": "Symposium on Cloud Computing"},
    "MobiCom": {"dblp_key": "conf/mobicom",  "org": "ACM",      "query": "MobiCom"},
    "MobiSys": {"dblp_key": "conf/mobisys",  "org": "ACM",      "query": "MobiSys"},
}

# Merge user-configured venues
_user_venues = daily_papers_config().get("conference_venues", [])
for v in _user_venues:
    name = v["name"]
    if name not in KNOWN_VENUES:
        KNOWN_VENUES[name] = {"dblp_key": v["dblp_key"], "org": "Unknown"}


CATEGORY_RULES = [
    ("LLM Serving & Inference", [
        "llm", "language model serving", "inference", "kv cache",
        "speculative decod", "model serving", "token", "decode",
        "prefill", "batching", "vllm",
    ]),
    ("Distributed Training", [
        "training", "checkpoint", "collective communication",
        "gradient", "data parallel", "model parallel", "pipeline parallel",
        "allreduce", "all-to-all", "gpu cluster",
    ]),
    ("Congestion Control & Transport", [
        "congestion control", "transport protocol", "tcp", "quic",
        "rdma", "cxl", "infiniband", "flow control", "ecn",
    ]),
    ("Datacenter Networking", [
        "datacenter", "data center", "hyperscale", "optical network",
        "topology", "fabric", "spine", "leaf", "clos",
    ]),
    ("Traffic Engineering & WAN", [
        "traffic engineering", "wan", "backbone", "peering", "routing",
        "mpls", "segment routing", "bgp", "sdwan",
    ]),
    ("Network Monitoring & Measurement", [
        "monitor", "measurement", "observability", "telemetry",
        "anomaly", "troubleshoot", "diagnosis", "sketch",
    ]),
    ("Serverless & Cloud", [
        "serverless", "container", "microservice", "kubernetes",
        "function-as-a-service", "faas", "cloud native", "autoscal",
    ]),
    ("Storage & Databases", [
        "storage", "database", "ssd", "nvme", "file system",
        "key-value", "log-structured", "wal", "transaction",
        "replication", "consensus", "dedup", "block store", "caching",
    ]),
    ("Network Security & Verification", [
        "security", "attack", "intrusion", "privacy", "confidential",
        "verification", "formal", "testing", "fuzzing", "bug",
        "ebpf", "firewall", "encryption",
    ]),
    ("Programmable Networks", [
        "p4", "programmable switch", "smartnic", "dpu", "fpga",
        "network function", "nfv",
    ]),
    ("Scheduling & Resource Management", [
        "scheduling", "resource manag", "allocation", "placement",
        "load balanc", "cluster manag", "orchestrat",
    ]),
    ("Video & Streaming", [
        "video", "streaming", "adaptive bitrate", "abr",
        "real-time communication", "rtc", "encoding",
    ]),
    ("Wireless & Mobile", [
        "wireless", "5g", "wifi", "wi-fi", "bluetooth", "ble",
        "cellular", "mobile", "spectrum", "mimo", "rfid",
    ]),
]


def categorize_paper(title: str, abstract: str = "") -> str:
    text = (title + " " + abstract).lower()
    for cat_name, keywords in CATEGORY_RULES:
        if any(kw in text for kw in keywords):
            return cat_name
    return "Other"


def resolve_venue(name: str) -> dict | None:
    upper = name.upper()
    for k, v in KNOWN_VENUES.items():
        if k.upper() == upper:
            result = {"name": k, **v}
            result.setdefault("query", k)
            return result
    return None


def _parse_hits(hits: list, dblp_key: str, venue_name: str, year: int,
                 seen_titles: set[str]) -> list[dict]:
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

        paper = {
            "title": title,
            "authors": authors,
            "url": paper_url,
            "venue": venue_name,
            "year": str(info.get("year", year)),
            "source": f"dblp-{venue_name}",
            "abstract": "",
            "affiliations": "",
            "pdf": "",
            "date": f"{year}-01-01",
            "category": "",
            "score": 0,
        }

        paper["score"] = max(score_paper(paper), 0)
        paper["category"] = categorize_paper(title)
        papers.append(paper)
    return papers


def fetch_conference(venue_name: str, dblp_key: str, year: int,
                     search_query: str | None = None) -> list[dict]:
    q_term = search_query or venue_name
    query = quote_plus(f"{q_term} {year}")
    page_size = 1000
    max_pages = 10

    papers = []
    seen_titles: set[str] = set()

    for page in range(max_pages):
        offset = page * page_size
        url = (f"https://dblp.org/search/publ/api?"
               f"q={query}&h={page_size}&f={offset}&format=json")

        if page == 0:
            print(f"  Fetching {venue_name} {year} from DBLP...", file=sys.stderr)
        else:
            print(f"  Fetching page {page + 1}...", file=sys.stderr)
            time.sleep(1.0)

        raw = fetch_url(url, timeout=30)
        if not raw:
            print(f"  [ERROR] Failed to fetch from DBLP (page {page + 1})", file=sys.stderr)
            break

        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            print(f"  [ERROR] Invalid JSON from DBLP", file=sys.stderr)
            break

        total = int(data.get("result", {}).get("hits", {}).get("@total", "0"))
        hits = data.get("result", {}).get("hits", {}).get("hit", [])

        if page == 0:
            print(f"  DBLP: {total} total hits", file=sys.stderr)

        if not hits:
            break

        page_papers = _parse_hits(hits, dblp_key, venue_name, year, seen_titles)
        papers.extend(page_papers)

        if offset + len(hits) >= total:
            break

    papers.sort(key=lambda p: (-p["score"], p["category"], p["title"]))
    print(f"  {venue_name} {year}: {len(papers)} papers", file=sys.stderr)
    return papers


def format_markdown(papers: list[dict], venue: str, year: int) -> str:
    lines = [f"# {venue} {year} — {len(papers)} papers\n"]

    categories: dict[str, list[dict]] = {}
    for p in papers:
        cat = p["category"]
        categories.setdefault(cat, []).append(p)

    cat_order = [name for name, _ in CATEGORY_RULES] + ["Other"]
    for cat in cat_order:
        cat_papers = categories.get(cat, [])
        if not cat_papers:
            continue
        lines.append(f"\n## {cat} ({len(cat_papers)})\n")
        for p in cat_papers:
            score_tag = f" ⭐{p['score']}" if p["score"] >= 3 else ""
            lines.append(f"- **{p['title']}**{score_tag}")
            lines.append(f"  - {p['authors'][:80]}")
            lines.append(f"  - [Link]({p['url']})")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Fetch conference papers from DBLP")
    parser.add_argument("--venue", help="Conference name (e.g., NSDI, SOSP, OSDI)")
    parser.add_argument("--year", type=int, default=datetime.now().year,
                        help="Year (default: current year)")
    parser.add_argument("--format", choices=["json", "markdown"], default="json",
                        help="Output format (default: json)")
    parser.add_argument("--list-venues", action="store_true",
                        help="List all known conference venues")
    args = parser.parse_args()

    if args.list_venues:
        for name, info in sorted(KNOWN_VENUES.items()):
            print(f"  {name:10s}  {info['org']:10s}  dblp: {info['dblp_key']}")
        return

    if not args.venue:
        parser.error("--venue is required (use --list-venues to see options)")

    venue_info = resolve_venue(args.venue)
    if not venue_info:
        print(f"Unknown venue: {args.venue}", file=sys.stderr)
        print(f"Known venues: {', '.join(sorted(KNOWN_VENUES.keys()))}", file=sys.stderr)
        sys.exit(1)

    papers = fetch_conference(venue_info["name"], venue_info["dblp_key"], args.year,
                              search_query=venue_info.get("query"))

    if args.format == "markdown":
        print(format_markdown(papers, venue_info["name"], args.year))
    else:
        import io
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
        json.dump(papers, sys.stdout, ensure_ascii=False, indent=2)
        print()


if __name__ == "__main__":
    main()
