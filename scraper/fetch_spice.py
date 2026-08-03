"""Collect structured Miami Spice data from official GMCVB listings.

Examples (from the repository root):
    python scraper/fetch_spice.py --list
    python scraper/fetch_spice.py claudie-restaurant --dry-run
    python scraper/fetch_spice.py --all

Downloaded pages are cached under scraper/.cache, which is gitignored. The
normalized data file is written atomically after every requested page runs.
"""

import argparse
import json
import re
import sys
import time
from datetime import date
from pathlib import Path
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup


BASE = "https://www.miamiandbeaches.com/l/eat-and-drink/"
ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data" / "spice-data.json"
CACHE = Path(__file__).resolve().parent / ".cache" / "html"
USER_AGENT = "Mozilla/5.0 (compatible; miami-spice-decoded/1.0; personal research project)"
DAY_BY_LABEL = {"MON": 1, "TUE": 2, "WED": 3, "THU": 4, "FRI": 5, "SAT": 6, "SUN": 0}
TIER_PATTERN = re.compile(r"(Brunch|Lunch|Dinner|Reserve(?: Dinner)?)\s*\$\s*([0-9,]+)", re.I)
SUPPLEMENT_PATTERN = re.compile(r"\+\s*\$\s*([0-9]+(?:\.[0-9]{1,2})?)")


def normalized_name(value):
    return re.sub(r"[^a-z0-9]", "", value.lower())


def slug_key(value):
    return value.strip("/").split("/")[0]


def load_data():
    return json.loads(DATA.read_text(encoding="utf-8"))


def all_entries(data):
    return data["decoded"] + data["tiersOnly"] + data["roster"]


def find_entries(data, requested, scrape_all=False):
    entries = all_entries(data)
    if scrape_all:
        return entries

    selected = []
    missing = []
    by_slug = {slug_key(entry["slug"]): entry for entry in entries}
    by_name = {normalized_name(entry["name"]): entry for entry in entries}
    for value in requested:
        entry = by_slug.get(slug_key(value)) or by_name.get(normalized_name(value))
        if entry and entry not in selected:
            selected.append(entry)
        elif not entry:
            missing.append(value)
    if missing:
        raise ValueError(f"not found in data file: {', '.join(missing)}")
    return selected


class Collector:
    def __init__(self, refresh=False, delay=1.0):
        self.refresh = refresh
        self.delay = delay
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT})
        self.last_request_at = None

    def get_listing(self, entry):
        cache_file = CACHE / f"{slug_key(entry['slug'])}.html"
        if cache_file.exists() and not self.refresh:
            return cache_file.read_text(encoding="utf-8")

        if self.last_request_at is not None:
            elapsed = time.monotonic() - self.last_request_at
            if elapsed < self.delay:
                time.sleep(self.delay - elapsed)
        url = BASE + entry["slug"].lstrip("/")
        response = self.session.get(url, timeout=30)
        self.last_request_at = time.monotonic()
        response.raise_for_status()
        CACHE.mkdir(parents=True, exist_ok=True)
        cache_file.write_text(response.text, encoding="utf-8")
        return response.text


def parse_schedule(spice):
    table = spice.select_one("table")
    if not table:
        return []

    labels = [cell.get_text(" ", strip=True).upper() for cell in table.select("thead th")][1:]
    tiers = []
    for row in table.select("tbody tr"):
        cells = row.select("th, td")
        if not cells:
            continue
        match = TIER_PATTERN.search(cells[0].get_text(" ", strip=True))
        if not match:
            continue
        meal = match.group(1).lower().replace(" dinner", "")
        days = []
        for label, cell in zip(labels, cells[1:]):
            marker = cell.get_text(" ", strip=True)
            if label in DAY_BY_LABEL and marker not in {"", "-", "–", "—"}:
                days.append(DAY_BY_LABEL[label])
        tiers.append({"meal": meal, "price": int(match.group(2).replace(",", "")), "days": sorted(days) or None})
    return tiers


def parse_menu_pane(pane):
    courses = []
    for group in pane.select(".ys-partner-details__tabs__container__info__temptation__group"):
        heading = group.select_one(".ys-partner-details__tabs__container__info__temptation__group__name")
        if not heading:
            continue
        instruction = group.select_one(".ys-partner-details__tabs__container__info__temptation__group__description")
        choices = []
        for item in group.select(".ys-partner-details__tabs__container__info__temptation__group__items__item"):
            name = item.select_one(".item-name")
            if not name:
                continue
            description = item.select_one(".item-description")
            choice = {"name": name.get_text(" ", strip=True)}
            if description and description.get_text(" ", strip=True):
                choice["description"] = description.get_text(" ", strip=True)
            supplement = SUPPLEMENT_PATTERN.search(choice["name"])
            if supplement:
                amount = float(supplement.group(1))
                choice["supplement"] = int(amount) if amount.is_integer() else amount
            choices.append(choice)
        if choices:
            course = {"course": heading.get_text(" ", strip=True), "choices": choices}
            if instruction and instruction.get_text(" ", strip=True):
                course["instruction"] = instruction.get_text(" ", strip=True)
            courses.append(course)
    return courses


def parse_menus(spice):
    menus = {}
    for pane in spice.select("[id$='menu']"):
        match = re.match(r"(brunch|lunch|dinner|reserve)(?:-([0-9]+))?menu$", pane.get("id", ""), re.I)
        if not match:
            continue
        courses = parse_menu_pane(pane)
        if courses:
            menus[(match.group(1).lower(), int(match.group(2)) if match.group(2) else None)] = courses
    return menus


def restaurant_url(soup):
    for link in soup.find_all("a", href=True):
        if link.get_text(" ", strip=True).lower() == "visit website":
            url = link["href"]
            if urlparse(url).scheme in {"http", "https"}:
                return url
    return None


def parse_listing(entry, html):
    soup = BeautifulSoup(html, "html.parser")
    spice = soup.select_one("#profile-spice")
    if not spice:
        raise ValueError("Miami Spice section not found")
    tiers = parse_schedule(spice)
    if not tiers:
        raise ValueError("participation schedule not found")
    menus = parse_menus(spice)
    for tier in tiers:
        menu = menus.get((tier["meal"], tier["price"])) or menus.get((tier["meal"], None))
        if menu:
            tier["spiceMenu"] = menu
    result = {
        "name": entry["name"],
        "area": entry["area"],
        "slug": entry["slug"],
        "tiers": tiers,
        "srcUrl": BASE + entry["slug"].lstrip("/"),
        "capturedAt": date.today().isoformat(),
    }
    website = restaurant_url(soup)
    if website:
        result["restaurantUrl"] = website
    return result


def merge(data, results, dry_run=False):
    decoded_indexes = {normalized_name(entry["name"]): index for index, entry in enumerate(data["decoded"])}
    tier_indexes = {normalized_name(entry["name"]): index for index, entry in enumerate(data["tiersOnly"])}
    promoted_names = set()
    demoted = []
    added = updated = decoded_updated = 0

    for result in results:
        key = normalized_name(result["name"])
        if key in decoded_indexes:
            decoded = data["decoded"][decoded_indexes[key]]
            valued_tiers = {(tier["meal"], tier["price"]): tier for tier in decoded["tiers"]}
            refreshed_tiers = []
            pending_tiers = []
            for official_tier in result["tiers"]:
                valued = valued_tiers.get((official_tier["meal"], official_tier["price"]))
                if valued:
                    valued.update({"days": official_tier["days"]})
                    if official_tier.get("spiceMenu"):
                        valued["spiceMenu"] = official_tier["spiceMenu"]
                    refreshed_tiers.append(valued)
                else:
                    pending_tiers.append(official_tier)
                    print(f"  + {result['name']}: official {official_tier['meal']} ${official_tier['price']} added as value pending")
            stale = set(valued_tiers) - {(tier["meal"], tier["price"]) for tier in result["tiers"]}
            for meal, price in sorted(stale):
                print(f"  - {result['name']}: removed stale decoded {meal} ${price}")
            if refreshed_tiers:
                decoded["tiers"] = refreshed_tiers
                decoded["pendingTiers"] = pending_tiers
                decoded["srcUrl"] = result["srcUrl"]
                decoded["capturedAt"] = result["capturedAt"]
                if result.get("restaurantUrl"):
                    decoded["restaurantUrl"] = result["restaurantUrl"]
                decoded_updated += 1
            else:
                demoted.append((key, result))
                print(f"  ↓ {result['name']}: no current valued tiers; demoted to value pending")
        elif key in tier_indexes:
            data["tiersOnly"][tier_indexes[key]].update(result)
            updated += 1
        else:
            data["tiersOnly"].append(result)
            tier_indexes[key] = len(data["tiersOnly"]) - 1
            promoted_names.add(key)
            added += 1

    if demoted:
        demoted_keys = {key for key, _ in demoted}
        data["decoded"] = [entry for entry in data["decoded"] if normalized_name(entry["name"]) not in demoted_keys]
        for key, result in demoted:
            if key in tier_indexes:
                data["tiersOnly"][tier_indexes[key]].update(result)
                updated += 1
            else:
                data["tiersOnly"].append(result)
                tier_indexes[key] = len(data["tiersOnly"]) - 1
                added += 1

    if promoted_names:
        data["roster"] = [entry for entry in data["roster"] if normalized_name(entry["name"]) not in promoted_names]
    data["meta"]["captured"] = date.today().isoformat()

    if not dry_run:
        temporary = DATA.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        temporary.replace(DATA)
    action = "would merge" if dry_run else "merged"
    print(f"{action}: {added} promoted, {updated} tier-only updated, {decoded_updated} decoded refreshed")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("slugs", nargs="*", help="stored slug or restaurant name")
    parser.add_argument("--list", action="store_true", help="list records available in the data file")
    parser.add_argument("--all", action="store_true", help="scrape every decoded, tier-only and roster-only record")
    parser.add_argument("--dry-run", action="store_true", help="parse and report without changing the data file")
    parser.add_argument("--refresh", action="store_true", help="ignore cached HTML and download pages again")
    parser.add_argument("--limit", type=int, help="process at most this many records")
    parser.add_argument("--delay", type=float, default=1.0, help="minimum seconds between downloads (default: 1)")
    args = parser.parse_args()

    data = load_data()
    if args.list:
        for entry in all_entries(data):
            print(f"{slug_key(entry['slug']):55} {entry['name']}")
        return
    if not args.all and not args.slugs:
        parser.error("provide one or more slugs, or use --all")
    try:
        entries = find_entries(data, args.slugs, args.all)
    except ValueError as error:
        parser.error(str(error))
    if args.limit is not None:
        entries = entries[: max(0, args.limit)]

    collector = Collector(refresh=args.refresh, delay=max(0, args.delay))
    results = []
    failures = []
    for index, entry in enumerate(entries, 1):
        print(f"[{index}/{len(entries)}] {entry['name']}")
        try:
            result = parse_listing(entry, collector.get_listing(entry))
            menu_count = sum(bool(tier.get("spiceMenu")) for tier in result["tiers"])
            print(f"  {len(result['tiers'])} tier(s), {menu_count} structured menu(s)")
            results.append(result)
        except (requests.RequestException, ValueError, OSError) as error:
            print(f"  ! {error}")
            failures.append((entry["name"], str(error)))

    merge(data, results, args.dry_run)
    if failures:
        print(f"{len(failures)} failure(s):", file=sys.stderr)
        for name, error in failures:
            print(f"  {name}: {error}", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()