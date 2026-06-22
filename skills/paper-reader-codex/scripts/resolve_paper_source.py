#!/usr/bin/env python3
"""Normalize paper inputs into a structured source description."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from urllib.parse import urlparse


DOI_RE = re.compile(r"10\.\d{4,9}/[-._;()/:A-Z0-9]+", re.IGNORECASE)
ARXIV_RE = re.compile(r"(?:arxiv\.org/(?:abs|pdf|html)/)(\d{4}\.\d{4,5})(?:v\d+)?", re.IGNORECASE)


def normalize_doi(value: str) -> str:
    match = DOI_RE.search(value.strip())
    return match.group(0) if match else ""


def build_pdf_result(raw: str, path: Path) -> dict:
    return {
        "ok": True,
        "input": raw,
        "type": "local_pdf",
        "pdf_path": str(path.resolve()),
        "publisher_hint": "",
        "doi": "",
        "arxiv_id": "",
        "url": "",
        "normalized_input": str(path.resolve()),
    }


def build_url_result(raw: str, parsed) -> dict:
    normalized = parsed.geturl()
    hostname = (parsed.hostname or "").lower()
    doi = normalize_doi(normalized)
    arxiv_match = ARXIV_RE.search(normalized)
    arxiv_id = arxiv_match.group(1) if arxiv_match else ""

    source_type = "url"
    publisher_hint = ""

    if "arxiv.org" in hostname:
        source_type = "arxiv"
        publisher_hint = "arxiv"
    elif hostname == "doi.org":
        source_type = "doi"
    elif hostname == "dl.acm.org":
        source_type = "acm_dl"
        publisher_hint = "acm"

    return {
        "ok": True,
        "input": raw,
        "type": source_type,
        "pdf_path": "",
        "publisher_hint": publisher_hint,
        "doi": doi,
        "arxiv_id": arxiv_id,
        "url": normalized,
        "normalized_input": normalized,
    }


def resolve_input(raw: str) -> dict:
    candidate = raw.strip()
    if not candidate:
        return {"ok": False, "error": "empty_input", "message": "Input is empty."}

    local_path = Path(candidate).expanduser()
    if local_path.exists():
        if local_path.is_file() and local_path.suffix.lower() == ".pdf":
            return build_pdf_result(raw, local_path)
        return {
            "ok": False,
            "error": "unsupported_local_path",
            "message": f"Path exists but is not a PDF: {local_path}",
        }

    parsed = urlparse(candidate)
    if parsed.scheme in {"http", "https"} and parsed.netloc:
        return build_url_result(raw, parsed)

    doi = normalize_doi(candidate)
    if doi:
        return {
            "ok": True,
            "input": raw,
            "type": "doi",
            "pdf_path": "",
            "publisher_hint": "acm" if doi.lower().startswith("10.1145/") else "",
            "doi": doi,
            "arxiv_id": "",
            "url": f"https://doi.org/{doi}",
            "normalized_input": doi,
        }

    if candidate.lower().endswith(".pdf"):
        return {
            "ok": False,
            "error": "missing_pdf",
            "message": f"PDF path does not exist: {local_path}",
        }

    return {
        "ok": True,
        "input": raw,
        "type": "title_or_query",
        "pdf_path": "",
        "publisher_hint": "",
        "doi": "",
        "arxiv_id": "",
        "url": "",
        "normalized_input": candidate,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Resolve a paper input into a normalized source record.")
    parser.add_argument("paper_input", help="Local PDF path, DOI, ACM URL, arXiv URL, or title-like input")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON output")
    args = parser.parse_args()

    result = resolve_input(args.paper_input)
    if args.pretty:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(json.dumps(result, ensure_ascii=False))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
