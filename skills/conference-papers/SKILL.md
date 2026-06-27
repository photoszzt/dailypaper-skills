---
name: conference-papers
description: |
  Browse and explore papers from a specific systems conference (NSDI, SOSP, OSDI,
  SIGCOMM, EuroSys, ASPLOS, FAST, MLSys, etc.). Fetches the full paper list from
  DBLP, scores by relevance, and categorizes by topic.

  Use when: "看一下 NSDI 2026", "browse SOSP 2025 papers", "OSDI 2026 文章",
  "show me SIGCOMM papers", "conference-papers FAST 2025", "what's in EuroSys this year",
  or any request to browse/list/explore papers from a specific conference.

  NOT for: daily arXiv monitoring (use daily-papers), reading a single paper (use paper-reader).
---

# Conference Paper Browser

Fetch, score, and categorize all papers from a systems conference proceeding.

**Output language: English.** All summaries, categories, evaluations, and saved files must be in English.

## Step 0: Read config

Read `../_shared/user-config.json` (and `user-config.local.json` if present) for:
- `VAULT_PATH`, `DAILY_PAPERS_PATH`
- Keywords and scoring config (used to highlight relevant papers)

## Step 1: Parse user input

Extract **venue name** and **year** from the user's request:
- "看一下 NSDI 2026" → venue=NSDI, year=2026
- "browse SOSP papers" → venue=SOSP, year=current year
- "OSDI 2025 文章" → venue=OSDI, year=2025

If venue is ambiguous, run `python3 fetch_conference.py --list-venues` to show options.

## Step 2: Fetch papers

```bash
python3 fetch_conference.py --venue {VENUE} --year {YEAR} --format json > /tmp/conference_{venue}_{year}.json
```

The script:
1. Queries DBLP search API for the conference
2. Filters by DBLP venue key (ensures only papers from the actual conference, not workshops with similar names)
3. Scores each paper against user's configured keywords
4. Auto-categorizes by topic (LLM Serving, Storage, Networking, Security, etc.)
5. Outputs sorted by relevance score then category

Progress logs go to stderr, results to stdout.

## Step 3: Present results

Show the user a **categorized summary** with counts per category. For each category, list the papers with:
- Title (bold)
- Score indicator (⭐ for score ≥ 3, i.e., particularly relevant to user's interests)
- Authors (first 2-3 names + "et al." if long)
- Link

Group by category. Order categories by relevance to user's configured research interests.

At the end, show a quick stats line:
```
{venue} {year}: {total} papers | {N} highly relevant (score ≥ 3) | Top categories: X (N), Y (N), Z (N)
```

## Step 4: User interaction

After presenting, the user may:

1. **Ask to read specific papers** — route to the appropriate reader:
   - If paper URL contains `arxiv.org` → `/paper-reader`
   - If paper URL contains `usenix.org` → first search arXiv for the title (many USENIX papers have arXiv preprints), then use `/paper-reader` with the arXiv or USENIX URL
   - If paper URL contains `doi.org` or `dl.acm.org` → first search arXiv for the title, if not found use `/paper-reader-codex`
   - If all automated sources fail → tell the user the URL and ask them to download the PDF manually

2. **Ask to save the list** — save as markdown to `{DAILY_PAPERS_PATH}/{VENUE}-{YEAR}.md`

3. **Ask to filter** — re-display with additional keyword filters

## Available venues

The script includes 25+ built-in venues. User-configured venues from `conference_venues` in `user-config.json` are merged in automatically. Run `--list-venues` to see all.

Core systems venues: SOSP, OSDI, NSDI, FAST, EuroSys, ASPLOS, ATC, SoCC
Networking: SIGCOMM, IMC, CoNEXT, INFOCOM, HotNets, MobiCom, MobiSys
Architecture: ISCA, MICRO, HPCA, SC
Databases: SIGMOD, VLDB
PL/Compilers: PLDI, PPoPP
ML Systems: MLSys
