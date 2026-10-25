"""Fetch arXiv metadata for one page of results and save it as CSV.

Docs: https://info.arxiv.org/help/api/user-manual.html (query interface)
Terms: https://info.arxiv.org/help/api/tou.html (max one request per 3 seconds)

Each row is one <entry>, stamped with the <id> of the <feed> it came from and the
UTC time of retrieval, so the same query can be fetched again later and compared.
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
COLUMNS = [
    "request_id",
    "retrieved_at",
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


def build_url(query, start=0, max_results=1000):
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
        try:
            request = urllib.request.Request(
                url, headers={"User-Agent": "arxiv-metadata-csv/0.1"}
            )
            with urllib.request.urlopen(request, timeout=120) as response:
                return response.read()
        except (urllib.error.URLError, TimeoutError) as exc:
            if attempt == attempts:
                raise
            print(f"retry {attempt}/{attempts - 1} after {exc}", file=sys.stderr)
            time.sleep(3)  # arXiv rate limit


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


def write_csv(rows, out):
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--query", default="cat:cs.LG", help="arXiv search_query")
    parser.add_argument("--max-results", type=int, default=1000)
    parser.add_argument("--out", type=Path, default=Path("data/arxiv_papers.csv"))
    args = parser.parse_args()
    if not 1 <= args.max_results <= MAX_PER_REQUEST:
        parser.error(f"--max-results must be 1..{MAX_PER_REQUEST}")

    retrieved_at = datetime.now(UTC).isoformat(timespec="seconds")
    rows = parse_entries(
        fetch(build_url(args.query, 0, args.max_results)), retrieved_at
    )
    write_csv(rows, args.out)
    print(f"{len(rows)} entries -> {args.out}")


if __name__ == "__main__":
    main()
