"""Fetch arXiv metadata with the SAME number of papers per domain and save it as CSV.

Docs: https://info.arxiv.org/help/api/user-manual.html (query interface)
Terms: https://info.arxiv.org/help/api/tou.html (max one request per 3 seconds)

Each row is one <entry>, stamped with the <id> of the <feed> it came from, the
UTC time of retrieval and the domain it was sampled for, so the same query can
be fetched again later and compared.

Balanced sampling: one quota per domain, filled page by page. A paper is kept
for a domain only if its PRIMARY category belongs to that domain, so a paper
cross-listed in several domains is never counted twice.
"""

import argparse
import csv
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from pathlib import Path

API_URL = "https://export.arxiv.org/api/query"
ATOM = "{http://www.w3.org/2005/Atom}"
ARXIV = "{http://arxiv.org/schemas/atom}"
MAX_PER_REQUEST = 2000  # arXiv API hard limit per slice
RATE_LIMIT = 3.0  # seconds between two requests (arXiv terms of use)

DOMAINS = {
    "cs": "cs.",
    "q-bio": "q-bio.",
    "physics": "physics.",
    "eess": "eess.",
}

COLUMNS = [
    "request_id",
    "retrieved_at",
    "domain",
    "arxiv_id",
    "title",
    "summary",
    "authors",
    "primary_category",
    "categories",
    "published",
    "updated",
    "abs_url",
    "pdf_url",
]

_last_request = 0.0


def throttle():
    """Block until at least RATE_LIMIT seconds passed since the previous request."""
    global _last_request
    wait = RATE_LIMIT - (time.monotonic() - _last_request)
    if wait > 0:
        time.sleep(wait)
    _last_request = time.monotonic()


def build_url(query, start=0, max_results=500):
    params = {
        "search_query": query,
        "start": start,
        "max_results": max_results,
        "sortBy": "submittedDate",
        "sortOrder": "descending",
    }
    return f"{API_URL}?{urllib.parse.urlencode(params)}"


def fetch(url, attempts=3):
    for attempt in range(1, attempts + 1):
        throttle()
        try:
            request = urllib.request.Request(
                url, headers={"User-Agent": "arxiv-metadata-csv/0.2"}
            )
            with urllib.request.urlopen(request, timeout=120) as response:
                return response.read()
        except (urllib.error.URLError, TimeoutError) as exc:
            if attempt == attempts:
                raise
            print(f"retry {attempt}/{attempts - 1} after {exc}", file=sys.stderr)


def text(node, tag):
    child = node.find(tag)
    return " ".join(child.text.split()) if child is not None and child.text else ""


def attr(node, tag, name):
    child = node.find(tag)
    return child.get(name, "") if child is not None else ""


def link(entry, rel, title=None):
    for node in entry.findall(f"{ATOM}link"):
        if node.get("rel") == rel and (title is None or node.get("title") == title):
            return node.get("href", "")
    return ""


def parse_entries(xml_bytes, retrieved_at):
    feed = ET.fromstring(xml_bytes)
    request_id = text(feed, f"{ATOM}id")
    rows = []
    for entry in feed.findall(f"{ATOM}entry"):
        abs_url = text(entry, f"{ATOM}id")
        if "/api/errors#" in abs_url:
            raise RuntimeError(f"arXiv API error: {text(entry, f'{ATOM}summary')}")
        rows.append(
            {
                "request_id": request_id,
                "retrieved_at": retrieved_at,
                "arxiv_id": abs_url.rsplit("/abs/", 1)[-1],
                "title": text(entry, f"{ATOM}title"),
                "summary": text(entry, f"{ATOM}summary"),
                "authors": "; ".join(
                    text(author, f"{ATOM}name")
                    for author in entry.findall(f"{ATOM}author")
                ),
                "primary_category": attr(entry, f"{ARXIV}primary_category", "term"),
                "categories": "; ".join(
                    node.get("term", "") for node in entry.findall(f"{ATOM}category")
                ),
                "published": text(entry, f"{ATOM}published"),
                "updated": text(entry, f"{ATOM}updated"),
                "abs_url": abs_url,
                "pdf_url": link(entry, "related", "pdf"),
            }
        )
    return rows


def date_clause(from_date, to_date):
    """Build an optional submittedDate filter (dates as YYYYMMDD)."""
    if not (from_date and to_date):
        return ""
    return f"submittedDate:[{from_date}0000 TO {to_date}2359]"


def fetch_domain(domain, quota, page_size, clause, retrieved_at, max_pages):
    """Collect up to `quota` papers whose primary category is in `domain`."""
    prefix = DOMAINS[domain]
    query = f"cat:{prefix}*"
    if clause:
        query += f" AND {clause}"

    rows, seen, start = [], set(), 0
    for _ in range(max_pages):
        page = parse_entries(fetch(build_url(query, start, page_size)), retrieved_at)
        if not page:
            break
        for row in page:
            if not row["primary_category"].startswith(prefix):
                continue
            if row["arxiv_id"] in seen:
                continue
            seen.add(row["arxiv_id"])
            row["domain"] = domain
            rows.append(row)
            if len(rows) == quota:
                return rows
        start += page_size
    return rows


def write_csv(rows, out):
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--domains", nargs="+", default=list(DOMAINS), choices=DOMAINS)
    parser.add_argument("--per-domain", type=int, default=500, help="quota per domain")
    parser.add_argument("--page-size", type=int, default=500)
    parser.add_argument("--max-pages", type=int, default=20, help="safety cap per domain")
    parser.add_argument("--from-date", help="YYYYMMDD, use together with --to-date")
    parser.add_argument("--to-date", help="YYYYMMDD, use together with --from-date")
    parser.add_argument("--out", type=Path, default=Path("data/arxiv_papers_v2.csv"))
    args = parser.parse_args()
    if not 1 <= args.page_size <= MAX_PER_REQUEST:
        parser.error(f"--page-size must be 1..{MAX_PER_REQUEST}")
    if bool(args.from_date) != bool(args.to_date):
        parser.error("--from-date and --to-date must be given together")

    retrieved_at = datetime.now(UTC).isoformat(timespec="seconds")
    clause = date_clause(args.from_date, args.to_date)

    all_rows = []
    for domain in args.domains:
        rows = fetch_domain(
            domain, args.per_domain, args.page_size, clause, retrieved_at, args.max_pages
        )
        print(f"{domain}: {len(rows)}/{args.per_domain}")
        if len(rows) < args.per_domain:
            print(f"warning: {domain} is under quota, sample is unbalanced", file=sys.stderr)
        all_rows.extend(rows)

    write_csv(all_rows, args.out)
    print(f"{len(all_rows)} entries -> {args.out}")


if __name__ == "__main__":
    main()