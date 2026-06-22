#!/usr/bin/env python3
"""Try to acquire an ACM DL PDF, preferring direct download and degrading clearly."""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse

import requests

_SHARED_DIR = Path(__file__).resolve().parents[2] / "_shared"
if str(_SHARED_DIR) not in sys.path:
    sys.path.insert(0, str(_SHARED_DIR))

from user_config import acm_download_dir, browser_executable_path, browser_profile_dir


DOI_RE = re.compile(r"10\.\d{4,9}/[-._;()/:A-Z0-9]+", re.IGNORECASE)
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

BROWSER_CANDIDATES = ("chromium", "chromium-browser", "google-chrome", "google-chrome-stable")


def playwright_available() -> bool:
    return importlib.util.find_spec("playwright") is not None


def node_playwright_available() -> bool:
    return shutil.which("npx") is not None


def detect_browser_executable() -> str | None:
    configured = browser_executable_path()
    if configured:
        configured = configured.expanduser()
        if configured.exists():
            return str(configured)

    for candidate in BROWSER_CANDIDATES:
        resolved = shutil.which(candidate)
        if resolved:
            return resolved
    return None


def ensure_node_playwright_package() -> str:
    runtime_dir = Path.home() / ".cache" / "paper-reader-codex" / "node-runtime"
    package_dir = runtime_dir / "node_modules" / "playwright"
    if package_dir.exists():
        return str(package_dir)

    runtime_dir.mkdir(parents=True, exist_ok=True)
    package_json = runtime_dir / "package.json"
    if not package_json.exists():
        package_json.write_text('{"name":"paper-reader-codex-runtime","private":true}\n', encoding="utf-8")

    subprocess.run(["npm", "install", "playwright"], cwd=runtime_dir, check=True, capture_output=True, text=True)
    return str(package_dir)


def ensure_node_playwright_browsers(playwright_module_dir: str) -> None:
    if detect_browser_executable():
        return

    module_dir = Path(playwright_module_dir)
    runtime_dir = module_dir.parent.parent
    marker = runtime_dir / ".chromium-installed"
    if marker.exists():
        return

    cli_path = module_dir / "cli.js"
    subprocess.run(
        ["node", str(cli_path), "install", "chromium"],
        cwd=runtime_dir,
        check=True,
        capture_output=True,
        text=True,
    )
    marker.write_text("ok\n", encoding="utf-8")


def normalize_doi(value: str) -> str:
    match = DOI_RE.search(value)
    return match.group(0) if match else ""


def source_urls(paper_input: str) -> tuple[str, str]:
    doi = normalize_doi(paper_input)
    if doi:
        return doi, f"https://dl.acm.org/doi/pdf/{doi}"

    parsed = urlparse(paper_input)
    if parsed.scheme in {"http", "https"} and parsed.netloc == "dl.acm.org":
        doi = normalize_doi(parsed.path)
        if doi:
            return doi, f"https://dl.acm.org/doi/pdf/{doi}"

    raise ValueError("Could not determine ACM DOI from input.")


def safe_filename(doi: str) -> str:
    return doi.replace("/", "_") + ".pdf"


def build_session(cookie_header: str | None) -> requests.Session:
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT, "Accept": "application/pdf,*/*"})
    if cookie_header:
        session.headers["Cookie"] = cookie_header
    return session


def write_pdf(content: bytes, output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(content)
    return output_path


def try_direct_download(pdf_url: str, output_path: Path, cookie_header: str | None) -> dict:
    session = build_session(cookie_header)
    response = session.get(pdf_url, timeout=30, allow_redirects=True)
    content_type = response.headers.get("content-type", "").lower()
    body_prefix = response.text[:256] if "text" in content_type or "html" in content_type else ""

    if response.ok and "application/pdf" in content_type:
        write_pdf(response.content, output_path)
        return {
            "ok": True,
            "method": "direct",
            "pdf_path": str(output_path.resolve()),
            "status_code": response.status_code,
            "content_type": content_type,
        }

    blocked = response.status_code in {401, 403, 429} or "cloudflare" in body_prefix.lower()
    return {
        "ok": False,
        "method": "direct",
        "status_code": response.status_code,
        "content_type": content_type,
        "blocked": blocked,
        "message": "Direct ACM PDF download did not return a PDF.",
    }


def browser_hint(doi: str, output_path: Path) -> dict:
    return {
        "ok": False,
        "method": "browser_required",
        "doi": doi,
        "landing_url": f"https://dl.acm.org/doi/{doi}",
        "pdf_url": f"https://dl.acm.org/doi/pdf/{doi}",
        "suggested_output_path": str(output_path.resolve()),
        "browser_profile_dir": str(browser_profile_dir()),
        "playwright_available": playwright_available(),
        "message": (
            "ACM blocked direct download in this environment. "
            "Use a persistent browser session to open the landing page, complete any login/challenge, "
            "then download the PDF to the suggested path."
        ),
    }


async def try_playwright_download(doi: str, output_path: Path, timeout_ms: int) -> dict:
    from playwright.async_api import TimeoutError as PlaywrightTimeoutError
    from playwright.async_api import async_playwright

    user_data_dir = browser_profile_dir().expanduser()
    user_data_dir.mkdir(parents=True, exist_ok=True)
    landing_url = f"https://dl.acm.org/doi/{doi}"
    executable_path = detect_browser_executable()

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch_persistent_context(
            user_data_dir=str(user_data_dir),
            headless=False,
            accept_downloads=True,
            executable_path=executable_path,
        )
        page = browser.pages[0] if browser.pages else await browser.new_page()
        await page.goto(landing_url, wait_until="domcontentloaded", timeout=timeout_ms)

        pdf_link = page.locator("a[href*='/doi/pdf/']").first
        try:
            await pdf_link.wait_for(state="visible", timeout=timeout_ms)
            async with page.expect_download(timeout=timeout_ms) as download_info:
                await pdf_link.click()
            download = await download_info.value
        except PlaywrightTimeoutError:
            await browser.close()
            return {
                "ok": False,
                "method": "playwright",
                "message": (
                    "Playwright reached the ACM landing page but did not capture a PDF download. "
                    "Complete login/challenge in the opened browser and click the PDF button manually."
                ),
                "landing_url": landing_url,
                "browser_profile_dir": str(user_data_dir),
                "browser_executable": executable_path,
            }

        output_path.parent.mkdir(parents=True, exist_ok=True)
        await download.save_as(str(output_path))
        await browser.close()
        return {
            "ok": True,
            "method": "playwright",
            "pdf_path": str(output_path.resolve()),
            "landing_url": landing_url,
            "browser_profile_dir": str(user_data_dir),
            "browser_executable": executable_path,
        }


def try_node_playwright_download(doi: str, output_path: Path, timeout_ms: int, headless: bool) -> dict:
    helper = Path(__file__).with_name("acquire_acm_pdf_playwright.cjs")
    try:
        playwright_module = ensure_node_playwright_package()
        ensure_node_playwright_browsers(playwright_module)
    except subprocess.CalledProcessError as exc:
        return {
            "ok": False,
            "method": "node-playwright",
            "message": "Failed to prepare Node Playwright runtime or browser binaries.",
            "stderr": (exc.stderr or "").strip(),
            "stdout": (exc.stdout or "").strip(),
        }

    command = [
        "node",
        str(helper),
        "--doi",
        doi,
        "--output-path",
        str(output_path),
        "--profile-dir",
        str(browser_profile_dir()),
        "--timeout-ms",
        str(timeout_ms),
        "--playwright-module",
        playwright_module,
    ]
    browser_executable = detect_browser_executable()
    if browser_executable:
        command.extend(["--browser-executable", browser_executable])
    if headless:
        command.append("--headless")

    proc = subprocess.run(command, capture_output=True, text=True)
    stdout = proc.stdout.strip()
    if stdout:
        try:
            return json.loads(stdout)
        except json.JSONDecodeError:
            return {
                "ok": False,
                "method": "node-playwright",
                "message": "Node Playwright returned non-JSON output.",
                "stdout": stdout,
                "stderr": proc.stderr.strip(),
            }

    return {
        "ok": False,
        "method": "node-playwright",
        "message": "Node Playwright did not produce output.",
        "stderr": proc.stderr.strip(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Acquire ACM Digital Library PDF content.")
    parser.add_argument("paper_input", help="ACM DOI, doi.org URL, or dl.acm.org URL")
    parser.add_argument("--output-dir", default=str(acm_download_dir()), help="Directory for downloaded PDFs")
    parser.add_argument("--cookie-header", default=os.environ.get("ACM_COOKIE", ""), help="Optional raw Cookie header")
    parser.add_argument(
        "--interactive-browser",
        action="store_true",
        help="If direct download is blocked and Playwright is installed, open a persistent browser to complete the download.",
    )
    parser.add_argument("--browser-timeout-ms", type=int, default=120000, help="Timeout for Playwright browser steps")
    parser.add_argument("--headless", action="store_true", help="Run Playwright browser headless for WSL or remote environments")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON output")
    args = parser.parse_args()

    try:
        doi, pdf_url = source_urls(args.paper_input)
    except ValueError as exc:
        result = {"ok": False, "error": "invalid_input", "message": str(exc)}
        print(json.dumps(result, ensure_ascii=False, indent=2 if args.pretty else None))
        return 1

    output_dir = Path(args.output_dir).expanduser()
    output_path = output_dir / safe_filename(doi)

    direct = try_direct_download(pdf_url, output_path, args.cookie_header or None)
    if direct["ok"]:
        print(json.dumps(direct, ensure_ascii=False, indent=2 if args.pretty else None))
        return 0

    if args.interactive_browser:
        result = None
        if playwright_available():
            try:
                result = asyncio.run(try_playwright_download(doi, output_path, args.browser_timeout_ms))
            except Exception as exc:
                result = {
                    "ok": False,
                    "method": "playwright",
                    "message": f"Playwright flow failed: {exc}",
                    "browser_profile_dir": str(browser_profile_dir()),
                }
        elif node_playwright_available():
            result = try_node_playwright_download(doi, output_path, args.browser_timeout_ms, args.headless)

        if result is not None:
            if result.get("ok"):
                print(json.dumps(result, ensure_ascii=False, indent=2 if args.pretty else None))
                return 0
            result["direct_attempt"] = direct
            print(json.dumps(result, ensure_ascii=False, indent=2 if args.pretty else None))
            return 1

    result = browser_hint(doi, output_path)
    result["direct_attempt"] = direct
    result["node_playwright_available"] = node_playwright_available()
    print(json.dumps(result, ensure_ascii=False, indent=2 if args.pretty else None))
    return 1


if __name__ == "__main__":
    sys.exit(main())
