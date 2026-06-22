# ACM Digital Library

Use this reference when the paper source is a DOI under `10.1145/...`, a `doi.org` redirect to ACM, or a `dl.acm.org` URL.

## Constraints

1. `dl.acm.org` may present a Cloudflare challenge to non-browser clients.
2. A `403` from direct HTTP does not mean the paper is unavailable.
3. Since January 1, 2026, ACM states that ACM Digital Library content is open access, but that does not remove browser-side access controls.

## Acquisition order

1. Try `python3 scripts/acquire_acm_pdf.py "<doi-or-url>"`.
2. If direct download succeeds, read the saved PDF.
3. If direct download fails with a browser-required result:
   - if Playwright is installed, rerun with `--interactive-browser`
   - if Chromium is installed in a non-standard location, set `paper_reader.browser_executable` in `../_shared/user-config.local.json`
   - in WSL without a visible Linux desktop, try `--interactive-browser --headless`, but expect some ACM challenges to require a headed browser
   - in headed mode, leave the browser open long enough to complete the ACM challenge; the script now waits for the PDF link until the browser timeout expires
   - open the `landing_url` in a normal browser
   - complete any login or anti-bot challenge
   - download the PDF to `suggested_output_path`
   - continue from the local PDF
4. If only the landing page metadata is available, limit the note to metadata plus abstract-level claims.

## Do not do

- Do not claim full-text findings when only the DOI landing page was reachable.
- Do not say ACM access is broken without naming whether the failure was `403`, `429`, missing cookies, or missing browser support.
- Do not assume arXiv-style HTML figures exist for ACM papers.

## Systems/database specifics

Many systems and database papers on ACM DL are PDF-first. Expect to extract:

- figures via `pdfimages`
- tables from the PDF text or manually
- venue and proceedings details from the first page
- evaluation setup from experiment sections rather than web metadata

## WSL notes

- Node Playwright is acceptable; the skill does not require the Python package.
- If WSLg is available, headed Chromium is the best ACM path.
- If WSL is headless, use the script to get the target paths and then complete the download manually from a normal browser if the challenge does not pass.
