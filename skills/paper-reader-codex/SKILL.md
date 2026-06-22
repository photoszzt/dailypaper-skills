---
name: paper-reader-codex
description: Read academic papers from ACM Digital Library, DOI links, arXiv links, local PDFs, or Zotero metadata and generate structured Obsidian notes in Codex. Use when the user asks to read, summarize, analyze, critique, or take notes on a paper; when a request includes a DOI, `dl.acm.org` URL, arXiv URL, PDF path, or Zotero paper reference; or when the task targets computer systems or database papers that need venue-aware, experiment-aware reading.
---

# Paper Reader Codex

## Overview

Use this skill to normalize a paper source, acquire readable content, and generate a structured note with systems/database-aware terminology and evaluation criteria.

Keep the existing `skills/paper-reader/` assets as source material. Use this skill as the Codex router and only load the additional references that match the current source and domain.

## Workflow

### 1. Load configuration

Read `../_shared/user-config.json`. If `../_shared/user-config.local.json` exists, let it override defaults.

Use these derived variables consistently:

- `VAULT_PATH`
- `NOTES_PATH`
- `CONCEPTS_PATH`
- `ZOTERO_DB`
- `ZOTERO_STORAGE`
- `DOMAIN_PROFILE`
- `ACM_DOWNLOAD_DIR`
- `BROWSER_PROFILE_DIR`
- `BROWSER_EXECUTABLE` if configured

Where:

- `NOTES_PATH = {VAULT_PATH}/{paper_notes_folder}`
- `CONCEPTS_PATH = {NOTES_PATH}/{concepts_folder}`

### 2. Resolve the source first

Run:

```bash
python3 scripts/resolve_paper_source.py "<user input>"
```

Support these inputs:

- local PDF path
- `https://arxiv.org/...`
- `https://doi.org/...`
- bare DOI such as `10.1145/3477132.3483587`
- `https://dl.acm.org/doi/...`
- Zotero-derived URL or DOI from `../paper-reader/assets/zotero_helper.py`

If the source is Zotero-driven, read `../paper-reader/references/zotero-guide.md` before touching the DB or attachment paths.

### 3. Acquire readable content

Follow this order:

1. If `type=local_pdf`, read the PDF directly.
2. If `type=arxiv`, prefer arXiv HTML for figures and fall back to the PDF.
3. If `type=acm_dl` or `publisher_hint=acm`, read `references/acm-digital-library.md` and run:

```bash
python3 scripts/acquire_acm_pdf.py "<doi-or-url>"
```

The ACM path has a hard constraint: direct HTTP often fails behind Cloudflare. Prefer a browser-assisted acquisition flow when direct download is blocked.

If ACM acquisition fails, do not pretend the full text was read. Say whether you only had metadata or whether the user needs to provide a local PDF.

### 4. Choose the reading profile

Default to `systems-db`.

Read `references/systems-db-terminology.md` when:

- the venue is SIGMOD, VLDB, SOSP, OSDI, NSDI, FAST, ATC, EuroSys, SoCC, ASPLOS, CIDR, or TODS
- the paper discusses transactions, storage engines, replication, scheduling, indexing, cache policy, memory disaggregation, distributed execution, or consistency
- the user explicitly says the paper is in systems, databases, storage, cloud, networking, or distributed systems

For non-systems papers, keep the note structure but do not force systems-specific metrics or terminology.

### 5. Generate the note

Use `assets/paper-note-template.md` as the note skeleton. Fill it completely enough that another engineer can skim:

- problem and constraints
- design or algorithm
- every important figure and table
- the experiments and what they prove
- limitations and hidden assumptions

For systems/database papers, explicitly capture:

- workload shape
- metrics such as throughput, latency, tail latency, recovery time, cost, memory footprint
- baselines and hardware/software environment
- correctness model or isolation/consistency assumptions
- deployment or failure model

Prefer local image extraction from the PDF when no stable HTML figure URLs exist. Reuse `../daily-papers/download_note_images.py` only when the note already contains image links that need repair.

### 6. Store and maintain notes

Save notes under `NOTES_PATH`, using the best method or system name available. If the canonical name is unclear, use `_待整理/`.

If the note introduces new concepts, create missing concept notes under `CONCEPTS_PATH`. For systems/database papers, concepts are often mechanisms, protocols, storage structures, failure models, or benchmark suites rather than vision model names.

Refresh indexes only when `auto_refresh_indexes=true`:

```bash
python3 ../_shared/generate_concept_mocs.py
python3 ../_shared/generate_paper_mocs.py
```

### 7. Be explicit about degraded reads

If you only had:

- abstract plus metadata
- DOI landing page without PDF
- a blocked ACM page

then state that the note is partial, name the missing source, and stop short of claims that require full-text access.

## Reusable resources

- `scripts/resolve_paper_source.py`: normalize local PDF, DOI, ACM, arXiv, and generic URLs
- `scripts/acquire_acm_pdf.py`: attempt direct ACM PDF download and fall back to browser-assisted acquisition
- `references/acm-digital-library.md`: ACM access strategy and failure handling
- `references/systems-db-terminology.md`: systems/database venues, metrics, and critique lenses
- `assets/paper-note-template.md`: generic note skeleton for systems/database papers

## Existing repo resources

Read these only when needed:

- `../paper-reader/references/zotero-guide.md` for Zotero lookup and attachment handling
- `../paper-reader/references/image-troubleshooting.md` when figure extraction from arXiv/PDF is failing
- `../paper-reader/assets/zotero_helper.py` when the user wants title lookup or collection traversal in Zotero
- `../daily-papers/download_note_images.py` when you already have note image URLs and need to localize broken links
