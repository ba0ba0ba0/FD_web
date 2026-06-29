#!/usr/bin/env python3
"""
Fault Diagnosis Papers Fetcher
================================
Fetches recent papers from Semantic Scholar and arXiv APIs,
categorized by research direction in the field of fault diagnosis.

Usage:
    python fetch_papers.py [--max-per-category N] [--output data/papers.json]

Environment variables:
    S2_API_KEY   Optional Semantic Scholar API key for higher rate limits
"""

import argparse
import hashlib
import json
import os
import re
import sys
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from typing import Optional

import requests

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Categories with their keyword queries for Semantic Scholar
CATEGORIES = {
    "deep_learning": {
        "name": "基于深度学习的方法",
        "name_en": "Deep Learning Based Methods",
        "icon": "🤖",
        "queries": [
            '"fault diagnosis" (CNN OR "convolutional neural network")',
            '"fault diagnosis" (transformer OR attention) (bearing OR gearbox OR rotating)',
            '"fault diagnosis" (LSTM OR GRU OR "recurrent neural network")',
            '"fault diagnosis" "graph neural network"',
            '"fault diagnosis" (autoencoder OR VAE)',
        ],
    },
    "transfer_learning": {
        "name": "迁移学习与域适应",
        "name_en": "Transfer Learning & Domain Adaptation",
        "icon": "🔄",
        "queries": [
            '"fault diagnosis" ("transfer learning" OR "domain adaptation")',
            '"fault diagnosis" ("domain generalization" OR "cross-domain")',
        ],
    },
    "federated_learning": {
        "name": "联邦学习与隐私保护",
        "name_en": "Federated Learning & Privacy Protection",
        "icon": "🔗",
        "queries": [
            '"fault diagnosis" ("federated learning" OR "privacy-preserving")',
            '"fault diagnosis" privacy "industrial IoT"',
        ],
    },
    "explainable_ai": {
        "name": "可解释性",
        "name_en": "Explainable AI",
        "icon": "🧠",
        "queries": [
            '"fault diagnosis" (explainable OR interpretable OR XAI)',
            '"fault diagnosis" (SHAP OR LIME OR "attention visualization")',
        ],
    },
    "application_deployment": {
        "name": "应用与部署",
        "name_en": "Application & Deployment",
        "icon": "🏭",
        "queries": [
            '"fault diagnosis" ("edge computing" OR lightweight OR "model compression")',
            '"fault diagnosis" ("knowledge distillation" OR "digital twin")',
            '"fault diagnosis" ("embedded system" OR FPGA OR "real-time")',
        ],
    },
}

# arXiv category filter for supplementary search
ARXIV_CATEGORIES = "cat:cs.LG OR cat:cs.AI OR cat:eess.SP OR cat:cs.CV OR cat:stat.ML"

S2_API_BASE = "https://api.semanticscholar.org/graph/v1"
S2_FIELDS = "title,authors,year,venue,abstract,externalIds,citationCount,publicationDate,openAccessPdf"
ARXIV_API_BASE = "http://export.arxiv.org/api/query"

# User-Agent required by arXiv
HEADERS = {
    "User-Agent": "FD-Papers-Collector/1.0 (mailto:fd-papers@example.com)",
}


def get_year_range():
    """Return (start_year, end_year) for the last 2 full years."""
    current_year = datetime.now(timezone.utc).year
    return (current_year - 2, current_year)


def normalize_title(title: str) -> str:
    """Normalize a title for deduplication comparison."""
    if not title:
        return ""
    t = title.lower()
    t = re.sub(r"[^a-z0-9\s]", "", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def title_hash(title: str) -> str:
    """Return a hash of the normalized title."""
    return hashlib.md5(normalize_title(title).encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Semantic Scholar API
# ---------------------------------------------------------------------------


def fetch_s2_papers(query: str, year_range: tuple, limit: int = 100, offset: int = 0) -> list[dict]:
    """
    Fetch papers from Semantic Scholar for a given query.
    Returns a list of raw paper dicts from the API response.
    """
    start_year, end_year = year_range
    url = f"{S2_API_BASE}/paper/search"
    params = {
        "query": query,
        "limit": min(limit, 100),
        "offset": offset,
        "fieldsOfStudy": "Engineering,Computer Science",
        "fields": S2_FIELDS,
        "year": f"{start_year}-{end_year}",
    }
    api_key = os.environ.get("S2_API_KEY")
    headers = HEADERS.copy()
    if api_key:
        headers["x-api-key"] = api_key

    resp = requests.get(url, params=params, headers=headers, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    return data.get("data", [])


def fetch_s2_with_retry(query: str, year_range: tuple, max_retries: int = 3) -> list[dict]:
    """Fetch from S2 with exponential backoff retry."""
    for attempt in range(max_retries):
        try:
            return fetch_s2_papers(query, year_range)
        except requests.exceptions.HTTPError as e:
            status = e.response.status_code if e.response else 0
            if status == 429:
                wait = int(e.response.headers.get("Retry-After", 30))
                print(f"  Rate limited (429), waiting {wait}s...")
                time.sleep(wait)
            elif status >= 500:
                wait = 2 ** (attempt + 1)
                print(f"  Server error ({status}), retrying in {wait}s...")
                time.sleep(wait)
            else:
                print(f"  HTTP {status}, skipping query: {query[:60]}...")
                return []
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
            wait = 2 ** (attempt + 1)
            print(f"  Connection error: {e}, retrying in {wait}s...")
            time.sleep(wait)
    print(f"  All retries exhausted for query: {query[:60]}...")
    return []


# ---------------------------------------------------------------------------
# arXiv API
# ---------------------------------------------------------------------------


def fetch_arxiv_papers(query: str, max_results: int = 50) -> list[dict]:
    """
    Fetch papers from arXiv API.
    Returns a list of paper dicts in our internal format.
    """
    url = ARXIV_API_BASE
    params = {
        "search_query": query,
        "start": 0,
        "max_results": max_results,
        "sortBy": "submittedDate",
        "sortOrder": "descending",
    }
    resp = requests.get(url, params=params, headers=HEADERS, timeout=30)
    resp.raise_for_status()

    # Parse Atom XML
    ns = {
        "atom": "http://www.w3.org/2005/Atom",
        "arxiv": "http://arxiv.org/schemas/atom",
    }
    root = ET.fromstring(resp.text)
    papers = []

    for entry in root.findall("atom:entry", ns):
        title_el = entry.find("atom:title", ns)
        title = title_el.text.strip().replace("\n", " ") if title_el is not None and title_el.text else ""

        # Authors
        authors = []
        for author_el in entry.findall("atom:author", ns):
            name_el = author_el.find("atom:name", ns)
            if name_el is not None and name_el.text:
                authors.append(name_el.text.strip())

        # Summary (abstract)
        summary_el = entry.find("atom:summary", ns)
        abstract = summary_el.text.strip().replace("\n", " ") if summary_el is not None and summary_el.text else ""

        # Published date
        published_el = entry.find("atom:published", ns)
        pub_date = published_el.text[:10] if published_el is not None and published_el.text else ""
        year = int(pub_date[:4]) if pub_date else 0

        # arXiv ID and URL
        id_el = entry.find("atom:id", ns)
        arxiv_id = ""
        arxiv_url = ""
        if id_el is not None and id_el.text:
            arxiv_url = id_el.text.strip()
            # Extract ID from URL like http://arxiv.org/abs/2401.12345
            arxiv_id = arxiv_url.split("/abs/")[-1] if "/abs/" in arxiv_url else arxiv_url

        # DOI if available
        doi = ""
        for link_el in entry.findall("atom:link", ns):
            href = link_el.get("href", "")
            if "doi.org" in href:
                doi = href.strip()

        # Categories
        cats = []
        for cat_el in entry.findall("atom:category", ns):
            term = cat_el.get("term", "")
            if term:
                cats.append(term)

        papers.append(
            {
                "title": title,
                "authors": authors,
                "year": year,
                "publicationDate": pub_date,
                "venue": "arXiv preprint",
                "abstract": abstract,
                "citationCount": 0,
                "externalIds": {"DOI": doi, "ArXiv": arxiv_id},
                "url": arxiv_url,
                "source": "arxiv",
                "arxivCategories": cats,
            }
        )

    return papers


def fetch_arxiv_with_retry(query: str, max_results: int = 50, max_retries: int = 3) -> list[dict]:
    """Fetch from arXiv with retry."""
    for attempt in range(max_retries):
        try:
            return fetch_arxiv_papers(query, max_results)
        except requests.exceptions.HTTPError as e:
            status = e.response.status_code if e.response else 0
            # arXiv returns 503 when busy
            if status in (429, 503):
                wait = (attempt + 1) * 5
                print(f"  arXiv busy (status {status}), waiting {wait}s...")
                time.sleep(wait)
            else:
                print(f"  arXiv HTTP {status}, skipping query: {query[:60]}...")
                return []
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
            wait = 2 ** (attempt + 1)
            print(f"  arXiv connection error: {e}, retrying in {wait}s...")
            time.sleep(wait)
    print(f"  arXiv all retries exhausted: {query[:60]}...")
    return []


# ---------------------------------------------------------------------------
# Paper Normalization & Deduplication
# ---------------------------------------------------------------------------


def normalize_s2_paper(raw: dict, category: str, all_matched_categories: list[str]) -> dict:
    """Convert a Semantic Scholar paper dict to our internal format."""
    authors = [a.get("name", "") for a in raw.get("authors", [])]
    ext_ids = raw.get("externalIds", {}) or {}
    doi = ext_ids.get("DOI", "")
    paper_id = raw.get("paperId", "")

    # Build URL: prefer DOI > Semantic Scholar URL
    url = ""
    if doi:
        url = f"https://doi.org/{doi}"
    elif paper_id:
        url = f"https://api.semanticscholar.org/CorpusID:{paper_id}"

    pub_date = raw.get("publicationDate", "")
    year = raw.get("year", 0) or 0

    return {
        "id": f"s2_{paper_id}" if paper_id else "",
        "title": raw.get("title", "").strip() if raw.get("title") else "",
        "authors": authors,
        "year": year,
        "publicationDate": pub_date,
        "venue": raw.get("venue", "") or "",
        "abstract": (raw.get("abstract", "") or "").strip(),
        "citationCount": raw.get("citationCount", 0) or 0,
        "externalIds": {"DOI": doi, "S2PaperId": paper_id},
        "url": url,
        "source": "semantic_scholar",
        "category": category,
        "matchedCategories": all_matched_categories,
    }


def normalize_arxiv_paper(raw: dict, category: str) -> dict:
    """Convert an arXiv paper dict to our internal format."""
    ext_ids = raw.get("externalIds", {}) or {}
    doi = ext_ids.get("DOI", "")
    arxiv_id = ext_ids.get("ArXiv", "")

    return {
        "id": f"ax_{arxiv_id}" if arxiv_id else "",
        "title": raw.get("title", "").strip(),
        "authors": raw.get("authors", []),
        "year": raw.get("year", 0),
        "publicationDate": raw.get("publicationDate", ""),
        "venue": "arXiv preprint",
        "abstract": raw.get("abstract", "").strip(),
        "citationCount": raw.get("citationCount", 0),
        "externalIds": {"DOI": doi, "ArXiv": arxiv_id},
        "url": raw.get("url", ""),
        "source": "arxiv",
        "category": category,
        "matchedCategories": [category],
    }


class Deduplicator:
    """Three-tier deduplication: DOI → S2 paperId → normalized title hash."""

    def __init__(self):
        self.seen_dois: set[str] = set()
        self.seen_s2ids: set[str] = set()
        self.seen_title_hashes: set[str] = set()

    def is_duplicate(self, paper: dict) -> bool:
        """Check if paper is a duplicate. Returns True if duplicate."""
        ext = paper.get("externalIds", {}) or {}
        doi = ext.get("DOI", "")
        s2id = ext.get("S2PaperId", "")
        t_hash = title_hash(paper.get("title", ""))

        # DOI match (strongest)
        if doi and doi in self.seen_dois:
            return True

        # S2 paperId match
        if s2id and s2id in self.seen_s2ids:
            return True

        # Title hash match
        if t_hash and t_hash in self.seen_title_hashes:
            return True

        return False

    def register(self, paper: dict):
        """Register a paper's identifiers as seen."""
        ext = paper.get("externalIds", {}) or {}
        doi = ext.get("DOI", "")
        s2id = ext.get("S2PaperId", "")
        t_hash = title_hash(paper.get("title", ""))

        if doi:
            self.seen_dois.add(doi)
        if s2id:
            self.seen_s2ids.add(s2id)
        if t_hash:
            self.seen_title_hashes.add(t_hash)


# ---------------------------------------------------------------------------
# Main Fetch Logic
# ---------------------------------------------------------------------------


def fetch_all_papers(max_per_query: int = 100) -> list[dict]:
    """
    Fetch all papers from both APIs, deduplicated and categorized.
    Returns list of paper dicts in our internal format.
    """
    year_range = get_year_range()
    print(f"Year range: {year_range[0]}–{year_range[1]}")
    print(f"Categories: {len(CATEGORIES)}")
    print()

    all_papers: list[dict] = []
    dedup = Deduplicator()

    has_api_key = bool(os.environ.get("S2_API_KEY"))
    sleep_between_s2 = 0.1 if has_api_key else 1.1

    # ---- Phase 1: Semantic Scholar ----
    for cat_id, cat_info in CATEGORIES.items():
        cat_name = cat_info["name"]
        print(f"[{cat_info['icon']}] {cat_name} ({cat_id})")
        cat_papers = []

        for query in cat_info["queries"]:
            print(f"  Querying S2: {query[:70]}...")
            raw_papers = fetch_s2_with_retry(query, year_range)

            for rp in raw_papers:
                paper = normalize_s2_paper(rp, cat_id, [cat_id])
                if not dedup.is_duplicate(paper):
                    dedup.register(paper)
                    cat_papers.append(paper)

            print(f"    → {len(raw_papers)} results, {len(cat_papers)} new unique so far")
            time.sleep(sleep_between_s2)

        all_papers.extend(cat_papers)
        print(f"  ✓ Category total: {len(cat_papers)} papers\n")

    print(f"After S2 phase: {len(all_papers)} total unique papers\n")

    # ---- Phase 2: arXiv supplementary ----
    print("--- arXiv Supplementary Phase ---")
    arxiv_count = 0

    for cat_id, cat_info in CATEGORIES.items():
        # Build broader arXiv query
        if cat_id == "deep_learning":
            query = f'all:"fault diagnosis" AND (all:deep+learning OR all:transformer OR all:LSTM) AND ({ARXIV_CATEGORIES})'
        elif cat_id == "transfer_learning":
            query = f'all:"fault diagnosis" AND (all:"transfer learning" OR all:"domain adaptation") AND ({ARXIV_CATEGORIES})'
        elif cat_id == "federated_learning":
            query = f'all:"fault diagnosis" AND all:"federated learning" AND ({ARXIV_CATEGORIES})'
        elif cat_id == "explainable_ai":
            query = f'all:"fault diagnosis" AND (all:explainable OR all:interpretable) AND ({ARXIV_CATEGORIES})'
        elif cat_id == "application_deployment":
            query = f'all:"fault diagnosis" AND (all:lightweight OR all:"edge computing" OR all:"digital twin") AND ({ARXIV_CATEGORIES})'
        else:
            continue

        print(f"  arXiv query: {query[:80]}...")
        raw_arxiv = fetch_arxiv_with_retry(query, max_results=50)

        for rp in raw_arxiv:
            paper = normalize_arxiv_paper(rp, cat_id)
            if not dedup.is_duplicate(paper) and paper["year"] >= year_range[0]:
                dedup.register(paper)
                all_papers.append(paper)
                arxiv_count += 1

        print(f"    → {len(raw_arxiv)} results, {arxiv_count} new from arXiv so far")
        time.sleep(3)  # arXiv rate limiting

    print(f"\nAfter arXiv phase: {len(all_papers)} total papers ({arxiv_count} new from arXiv)")

    return all_papers


def build_output(all_papers: list[dict]) -> dict:
    """Build the final output JSON structure."""
    # Sort by citation count desc, then year desc
    all_papers.sort(key=lambda p: (p.get("citationCount", 0) or 0, p.get("year", 0) or 0), reverse=True)

    # Category stats
    cat_counts = {}
    for p in all_papers:
        cat = p["category"]
        cat_counts[cat] = cat_counts.get(cat, 0) + 1

    # Source counts
    s2_count = sum(1 for p in all_papers if p["source"] == "semantic_scholar")
    ax_count = sum(1 for p in all_papers if p["source"] == "arxiv")

    # Year distribution
    year_dist = {}
    for p in all_papers:
        y = p.get("year", 0)
        if y:
            year_dist[str(y)] = year_dist.get(str(y), 0) + 1

    # Build category objects for the frontend
    categories_output = []
    for cat_id, cat_info in CATEGORIES.items():
        cat_papers = [p for p in all_papers if p["category"] == cat_id]
        categories_output.append(
            {
                "id": cat_id,
                "name": cat_info["name"],
                "nameEn": cat_info["name_en"],
                "icon": cat_info["icon"],
                "count": len(cat_papers),
                "paperIds": [p["id"] for p in cat_papers],
            }
        )

    return {
        "meta": {
            "lastUpdated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "totalPapers": len(all_papers),
            "yearRange": list(get_year_range()),
            "sources": {"semanticScholar": s2_count, "arxiv": ax_count},
            "categoryStats": cat_counts,
            "yearDistribution": year_dist,
        },
        "categories": categories_output,
        "papers": all_papers,
    }


def main():
    parser = argparse.ArgumentParser(description="Fetch fault diagnosis papers from academic APIs")
    parser.add_argument("--max-per-query", type=int, default=100, help="Max results per API query (default: 100)")
    parser.add_argument("--output", type=str, default="data/papers.json", help="Output JSON file path")
    parser.add_argument("--dry-run", action="store_true", help="Print summary without writing file")
    args = parser.parse_args()

    print("=" * 60)
    print("  Fault Diagnosis Papers Fetcher")
    print("=" * 60)
    print(f"  Time: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print(f"  Max per query: {args.max_per_query}")
    print()

    papers = fetch_all_papers(max_per_query=args.max_per_query)
    output = build_output(papers)

    print("\n" + "=" * 60)
    print("  Summary")
    print("=" * 60)
    print(f"  Total papers:          {output['meta']['totalPapers']}")
    print(f"  From Semantic Scholar: {output['meta']['sources']['semanticScholar']}")
    print(f"  From arXiv:            {output['meta']['sources']['arxiv']}")
    print(f"  Year distribution:     {output['meta']['yearDistribution']}")
    print(f"  Category breakdown:")
    for cat in output["categories"]:
        print(f"    {cat['icon']} {cat['name']}: {cat['count']}")

    if args.dry_run:
        print("\n[Dry run — no file written]")
    else:
        # Ensure output directory exists
        os.makedirs(os.path.dirname(args.output) if os.path.dirname(args.output) else ".", exist_ok=True)
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(output, f, ensure_ascii=False, indent=2)
        print(f"\n✓ Written to {args.output}")
        print(f"  File size: {os.path.getsize(args.output) / 1024:.1f} KB")


if __name__ == "__main__":
    main()
