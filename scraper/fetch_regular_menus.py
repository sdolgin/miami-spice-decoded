"""Build a review queue of à la carte price matches from restaurant menus.

Downloads are cached under scraper/.cache/menus. Candidate matches are written
to data/valuation-review.json; this script never promotes values automatically.

Examples:
    python scraper/fetch_regular_menus.py --domains northitalia.com bullagastrobar.com
    python scraper/fetch_regular_menus.py "North Italia - Aventura"
"""

import argparse
import hashlib
import io
import json
import re
import time
import unicodedata
from datetime import date
from difflib import SequenceMatcher
from pathlib import Path
from urllib.parse import urldefrag, urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from pypdf import PdfReader


ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data" / "spice-data.json"
OUTPUT = ROOT / "data" / "valuation-review.json"
CACHE = Path(__file__).resolve().parent / ".cache" / "menus"
USER_AGENT = "Mozilla/5.0 (compatible; miami-spice-decoded/1.0; personal research project)"
PRICE_AT_END = re.compile(r"(?:\$\s*)?(\d{1,3}(?:\s*\.\s*\d{0,2})?)\s*$")
PRICE_WITH_DOLLAR = re.compile(r"\$\s*(\d{1,3}(?:\.\d{1,2})?)")
EXCLUDED_LINK_WORDS = ("miami spice", "restaurant week", "happy hour", "beverage", "cocktail", "wine", "kids", "nutrition", "catering")
BULLA_PDF = "https://bullagastrobar.com/wp-content/pdf/MIABULL_ALL_Dinner.pdf"
BULLA_DESSERT_PDF = "https://bullagastrobar.com/wp-content/pdf/CG_Dessert.pdf"
BULLA_REVIEWED_PRICES = {
    "montaditos de salmon ahumado": (14, "MONTADITOS DE SALMÓN AHUMADO 14"),
    "huevos benedictinos": (16, "HUEVOS BENEDICTINOS - Smoked salmon 16"),
    "blueberry ricotta pancakes": (12, "BLUEBERRY & RICOTTA PANCAKES 12"),
    "churros con chocolate": (10, "CHURROS CON CHOCOLATE - 6 for 10"),
    "chicken breast con queso azul": (18.5, "Chicken breast 18.5"),
    "salmon": (27, "SALMÓN - Large 27"),
    "ensalada mediterranea": (13, "MEDITERRÁNEA 13"),
}


def normalized(value):
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    value = re.sub(r"\([^)]*(?:\+?\$|gf|vegan|vegetarian)[^)]*\)", " ", value, flags=re.I)
    value = re.sub(r"\+?\s*\$\s*\d+(?:\.\d+)?", " ", value)
    return " ".join(re.findall(r"[a-z0-9]+", value.lower()))


def cache_path(url, suffix):
    digest = hashlib.sha256(url.encode()).hexdigest()[:20]
    return CACHE / f"{digest}{suffix}"


class MenuClient:
    def __init__(self, refresh=False, delay=0.5):
        self.refresh = refresh
        self.delay = delay
        self.last_request_at = None
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT})

    def get(self, url):
        suffix = ".pdf" if urlparse(url).path.lower().endswith(".pdf") else ".html"
        path = cache_path(url, suffix)
        if path.exists() and not self.refresh:
            return path.read_bytes(), suffix
        if self.last_request_at is not None:
            elapsed = time.monotonic() - self.last_request_at
            if elapsed < self.delay:
                time.sleep(self.delay - elapsed)
        response = self.session.get(url, timeout=30)
        self.last_request_at = time.monotonic()
        response.raise_for_status()
        content_type = response.headers.get("content-type", "").lower()
        if "pdf" in content_type:
            suffix = ".pdf"
            path = cache_path(url, suffix)
        CACHE.mkdir(parents=True, exist_ok=True)
        path.write_bytes(response.content)
        return response.content, suffix


def discover_menu_urls(page_url, html):
    soup = BeautifulSoup(html, "html.parser")
    found = []
    for link in soup.find_all("a", href=True):
        url = urldefrag(urljoin(page_url, link["href"]))[0]
        label = " ".join(link.get_text(" ", strip=True).split())
        signal = f"{label} {url}".lower()
        if "menu" not in signal and ".pdf" not in signal:
            continue
        if any(word in signal for word in EXCLUDED_LINK_WORDS):
            continue
        if urlparse(url).scheme not in {"http", "https"}:
            continue
        if url not in found:
            found.append(url)
    return found[:12]


def candidate(name, price, source_url, context=""):
    if not name or not 3 <= price <= 300:
        return None
    return {"name": name.strip(" -–—|"), "price": price, "context": context.strip(), "sourceUrl": source_url}


def parse_price(value):
    return float(re.sub(r"\s+", "", value).rstrip("."))


def html_candidates(source_url, html):
    soup = BeautifulSoup(html, "html.parser")
    values = []
    seen = set()
    for item in soup.select(".menu-item"):
        name_node = item.select_one(".menu-item-name")
        if not name_node:
            continue
        header = item.select_one(".menu-item-header") or item
        match = PRICE_AT_END.search(header.get_text(" ", strip=True))
        if match:
            value = candidate(name_node.get_text(" ", strip=True), parse_price(match.group(1)), source_url, item.get_text(" ", strip=True))
            if value and (normalized(value["name"]), value["price"]) not in seen:
                seen.add((normalized(value["name"]), value["price"]))
                values.append(value)
    for text_node in soup.find_all(string=PRICE_WITH_DOLLAR):
        text = " ".join(text_node.parent.get_text(" ", strip=True).split())
        if len(text) > 180:
            continue
        matches = list(PRICE_WITH_DOLLAR.finditer(text))
        if len(matches) != 1:
            continue
        match = matches[0]
        name = text[: match.start()].strip(" -–—|:")
        value = candidate(name, parse_price(match.group(1)), source_url, text)
        key = (normalized(value["name"]), value["price"]) if value else None
        if value and len(normalized(name)) >= 3 and key not in seen:
            seen.add(key)
            values.append(value)
    return values


def pdf_candidates(source_url, content):
    text = "\n".join(page.extract_text() or "" for page in PdfReader(io.BytesIO(content)).pages)
    lines = [" ".join(line.split()) for line in text.splitlines() if line.strip()]
    values = []
    seen = set()
    for index, line in enumerate(lines):
        match = PRICE_AT_END.search(line)
        if not match:
            continue
        name = line[: match.start()].strip(" .-–—|:•")
        if ":" in name:
            name = name.split(":", 1)[0].strip()
        if len(normalized(name)) < 3 and index:
            name = lines[index - 1]
        value = candidate(name, parse_price(match.group(1)), source_url, " | ".join(lines[max(0, index - 1): index + 2]))
        key = (normalized(value["name"]), value["price"]) if value else None
        if value and len(normalized(value["name"])) >= 3 and key not in seen:
            seen.add(key)
            values.append(value)
    return values


def score_match(choice_name, regular_name):
    left = normalized(choice_name)
    right = normalized(regular_name)
    if not left or not right:
        return 0
    if left == right:
        return 1
    left_tokens = set(left.split())
    right_tokens = set(right.split())
    overlap = len(left_tokens & right_tokens) / len(left_tokens | right_tokens)
    sequence = SequenceMatcher(None, left, right).ratio()
    containment = min(len(left), len(right)) / max(len(left), len(right)) if left in right or right in left else 0
    return round(max(overlap, sequence * 0.9, containment * 0.95), 3)


def match_choice(choice, candidates):
    ranked = []
    for regular in candidates:
        confidence = score_match(choice["name"], regular["name"])
        if confidence < 0.42:
            continue
        supplement = choice.get("supplement", 0)
        ranked.append({
            "regularName": regular["name"],
            "regularPrice": regular["price"],
            "supplement": supplement,
            "effectiveValue": regular["price"] - supplement,
            "confidence": confidence,
            "sourceUrl": regular["sourceUrl"],
            "sourceText": regular["context"],
        })
    return sorted(ranked, key=lambda value: (-value["confidence"], value["regularPrice"]))[:3]


def select_entries(data, names, domains):
    entries = data["tiersOnly"] + data["decoded"]
    if names:
        wanted = {normalized(name) for name in names}
        return [entry for entry in entries if normalized(entry["name"]) in wanted]
    domains = tuple(domain.lower() for domain in domains)
    return [entry for entry in entries if entry.get("restaurantUrl") and any(domain in urlparse(entry["restaurantUrl"]).netloc.lower() for domain in domains)]


def collect_sources(entry, client):
    page_url = entry["restaurantUrl"]
    if "northitalia.com" in urlparse(page_url).netloc and urlparse(page_url).path in {"", "/"}:
        location = "miami-fl-dadeland" if "dadeland" in entry["name"].lower() else "miami-fl"
        page_url = f"https://www.northitalia.com/locations/{location}/"
    if "bullagastrobar.com" in urlparse(page_url).netloc and urlparse(page_url).path in {"", "/"}:
        location = entry["name"].removeprefix("Bulla Gastrobar ").lower().replace(" ", "-")
        page_url = f"https://bullagastrobar.com/menus/{location}/"
    content, suffix = client.get(page_url)
    urls = [page_url]
    if suffix == ".html":
        urls.extend(discover_menu_urls(page_url, content.decode("utf-8", errors="replace")))
    if "bullagastrobar.com" in urlparse(page_url).netloc:
        urls.extend([
            "https://bullagastrobar.com/wp-content/pdf/MIABULL_ALL_Brunch.pdf",
            "https://bullagastrobar.com/wp-content/pdf/CG_Lunch.pdf",
            "https://bullagastrobar.com/wp-content/pdf/MIABULL_ALL_Dinner.pdf",
            "https://bullagastrobar.com/wp-content/pdf/CG_Dessert.pdf",
        ])
    urls = list(dict.fromkeys(urls))
    sources = []
    candidates = []
    candidate_keys = set()
    failures = []
    for url in urls:
        try:
            content, suffix = client.get(url)
            extracted = pdf_candidates(url, content) if suffix == ".pdf" else html_candidates(url, content.decode("utf-8", errors="replace"))
            if extracted:
                sources.append({"url": url, "format": suffix[1:], "candidates": len(extracted)})
                for value in extracted:
                    key = (normalized(value["name"]), value["price"])
                    if key not in candidate_keys:
                        candidate_keys.add(key)
                        candidates.append(value)
        except Exception as error:
            failures.append({"url": url, "error": str(error)})
    return sources, candidates, failures


def build_review(entry, candidates, sources, failures):
    tiers = []
    for tier in entry["tiers"] + entry.get("pendingTiers", []):
        courses = []
        spice_menu = tier.get("spiceMenu", [])
        for course in spice_menu:
            choices = []
            for choice in course["choices"]:
                matches = match_choice(choice, candidates)
                reviewed = BULLA_REVIEWED_PRICES.get(normalized(choice["name"])) if "bullagastrobar.com" in entry["restaurantUrl"] else None
                if reviewed:
                    price, source_text = reviewed
                    supplement = choice.get("supplement", 0)
                    matches.insert(0, {
                        "regularName": choice["name"],
                        "regularPrice": price,
                        "supplement": supplement,
                        "effectiveValue": price - supplement,
                        "confidence": 1,
                        "sourceUrl": BULLA_DESSERT_PDF if "churros" in normalized(choice["name"]) else BULLA_PDF,
                        "sourceText": source_text,
                        "reviewed": True,
                    })
                choices.append({"spiceName": choice["name"], "matches": matches[:3], "decision": None})
            courses.append({"course": course["course"], "choices": choices})
        tiers.append({"meal": tier["meal"], "price": tier["price"], "courses": courses})
    return {
        "name": entry["name"],
        "slug": entry["slug"],
        "restaurantUrl": entry["restaurantUrl"],
        "sources": sources,
        "failures": failures,
        "tiers": tiers,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("names", nargs="*", help="exact restaurant names")
    parser.add_argument("--domains", nargs="+", default=[], help="restaurant website domains to process")
    parser.add_argument("--refresh", action="store_true", help="redownload regular menu sources")
    parser.add_argument("--delay", type=float, default=0.5, help="minimum seconds between downloads")
    args = parser.parse_args()
    if not args.names and not args.domains:
        parser.error("provide restaurant names or --domains")

    data = json.loads(DATA.read_text(encoding="utf-8"))
    entries = select_entries(data, args.names, args.domains)
    client = MenuClient(refresh=args.refresh, delay=max(0, args.delay))
    reviews = []
    for index, entry in enumerate(entries, 1):
        print(f"[{index}/{len(entries)}] {entry['name']}")
        try:
            sources, candidates, failures = collect_sources(entry, client)
            review = build_review(entry, candidates, sources, failures)
            matched = sum(bool(choice["matches"]) for tier in review["tiers"] for course in tier["courses"] for choice in course["choices"])
            total = sum(1 for tier in review["tiers"] for course in tier["courses"] for _ in course["choices"])
            print(f"  {len(sources)} priced source(s), {len(candidates)} candidates, {matched}/{total} choices matched")
            reviews.append(review)
        except Exception as error:
            print(f"  ! {error}")
            reviews.append({"name": entry["name"], "slug": entry["slug"], "restaurantUrl": entry.get("restaurantUrl"), "error": str(error), "tiers": []})

    output = {"generatedAt": date.today().isoformat(), "restaurants": reviews}
    OUTPUT.write_text(json.dumps(output, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {len(reviews)} restaurant review(s) to {OUTPUT}")


if __name__ == "__main__":
    main()