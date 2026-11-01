"""Catalog scraper -> CSV / JSON / Google Sheets (demo project).

Target: books.toscrape.com — a public sandbox site made for scraping practice.
Polite by default: 1 request per second, custom User-Agent, retries with backoff.

    python scraper.py                      # CSV + JSON into ./out
    python scraper.py --pages 5            # first 5 catalogue pages
    python scraper.py --sheet <SHEET_ID>   # also push to Google Sheets
                                           # (needs GOOGLE_APPLICATION_CREDENTIALS = service-account JSON)
"""
import argparse
import csv
import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

BASE = "https://books.toscrape.com/"
RATING = {"One": 1, "Two": 2, "Three": 3, "Four": 4, "Five": 5}
HEADERS = {"User-Agent": "portfolio-demo-scraper/1.0 (+https://github.com/)"}


@dataclass
class Book:
    title: str
    price_gbp: float
    rating: int
    in_stock: bool
    category: str
    url: str


def get(session: requests.Session, url: str, tries: int = 3) -> BeautifulSoup:
    for attempt in range(tries):
        try:
            r = session.get(url, headers=HEADERS, timeout=20)
            r.raise_for_status()
            r.encoding = "utf-8"
            time.sleep(1)  # rate limit
            return BeautifulSoup(r.text, "html.parser")
        except requests.RequestException:
            if attempt == tries - 1:
                raise
            time.sleep(2**attempt)


def categories(session) -> dict[str, str]:
    soup = get(session, BASE)
    links = soup.select("div.side_categories ul li ul li a")
    return {a.get_text(strip=True): urljoin(BASE, a["href"]) for a in links}


def scrape(pages: int) -> list[Book]:
    session = requests.Session()
    cat_of = {}
    # map each book URL to its category (category pages are cheap: 1–8 pages each)
    for name, url in categories(session).items():
        while url:
            soup = get(session, url)
            for a in soup.select("article.product_pod h3 a"):
                cat_of[urljoin(url, a["href"]).split("/catalogue/")[-1]] = name
            nxt = soup.select_one("li.next a")
            url = urljoin(url, nxt["href"]) if nxt else None

    books, url = [], urljoin(BASE, "catalogue/page-1.html")
    for _ in range(pages):
        soup = get(session, url)
        for pod in soup.select("article.product_pod"):
            a = pod.select_one("h3 a")
            link = urljoin(url, a["href"])
            books.append(
                Book(
                    title=a["title"],
                    price_gbp=float(pod.select_one(".price_color").get_text().lstrip("£Â")),
                    rating=RATING[pod.select_one("p.star-rating")["class"][1]],
                    in_stock="In stock" in pod.select_one(".availability").get_text(),
                    category=cat_of.get(link.split("/catalogue/")[-1], "Unknown"),
                    url=link,
                )
            )
        nxt = soup.select_one("li.next a")
        if not nxt:
            break
        url = urljoin(url, nxt["href"])
    return books


def to_sheets(books: list[Book], sheet_id: str) -> None:
    import gspread  # optional dependency

    ws = gspread.service_account().open_by_key(sheet_id).sheet1
    ws.clear()
    ws.update([list(asdict(books[0]).keys())] + [list(asdict(b).values()) for b in books])
    ws.format("A1:F1", {"textFormat": {"bold": True}})


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--pages", type=int, default=50)
    p.add_argument("--out", default="out")
    p.add_argument("--sheet")
    args = p.parse_args()

    books = scrape(args.pages)
    out = Path(args.out)
    out.mkdir(exist_ok=True)
    with open(out / "books.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(asdict(books[0]).keys()))
        w.writeheader()
        w.writerows(asdict(b) for b in books)
    (out / "books.json").write_text(json.dumps([asdict(b) for b in books], ensure_ascii=False))
    if args.sheet:
        to_sheets(books, args.sheet)
    print(f"{len(books)} books -> {out}/books.csv" + (" + Google Sheets" if args.sheet else ""))


if __name__ == "__main__":
    main()
