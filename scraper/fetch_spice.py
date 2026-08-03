"""
Miami Spice 2026 data collector.

Pulls verified tier/day/menu data from brickelldowntownliving.com (which mirrors
the official Spice menus per restaurant in a structured format) and merges it
into data/spice-data.json.

Usage (Windows, from the repo root):
    py scraper\fetch_spice.py --list          # show restaurant pages found on the index
    py scraper\fetch_spice.py --all           # scrape every page found, merge into data file
    py scraper\fetch_spice.py zuma-miami the-mexican-brickell-key   # scrape specific slugs

Notes:
- Be polite: the script sleeps 2s between requests.
- Scraped entries land in "tiersOnly" (tier + days + captured Spice menu text).
  Promoting one to a fully "decoded" card (with a la carte worth) is a manual
  editorial step in data/spice-data.json, because worth requires the regular menu.
- Sites change. If parsing breaks, run with --debug to dump the raw text.
"""
import argparse, json, re, sys, time
from pathlib import Path

import requests
from bs4 import BeautifulSoup

BASE = "https://brickelldowntownliving.com/miami-spice-2026/"
DATA = Path(__file__).resolve().parent.parent / "data" / "spice-data.json"
UA = {"User-Agent": "Mozilla/5.0 (spice-decoder; personal project; contact via GitHub)"}
DAY = {"sunday":0,"monday":1,"tuesday":2,"wednesday":3,"thursday":4,"friday":5,"saturday":6}
MEALS = ("brunch","lunch","dinner","reserve")

def get(url):
    r = requests.get(url, headers=UA, timeout=30)
    r.raise_for_status()
    return r.text

def list_pages():
    soup = BeautifulSoup(get(BASE), "html.parser")
    slugs = set()
    for a in soup.select("a[href*='/miami-spice-2026/']"):
        m = re.search(r"/miami-spice-2026/([a-z0-9\-]+)/?$", a.get("href",""))
        if m and m.group(1) != "miami-spice-2026":
            slugs.add(m.group(1))
    return sorted(slugs)

def parse_tiers(text):
    """Find lines like 'Lunch $40 Monday, Tuesday, ...' anywhere in the page text."""
    tiers = []
    for meal in MEALS:
        for m in re.finditer(rf"{meal}\s*\$([0-9]+)\s*((?:(?:sun|mon|tues|wednes|thurs|fri|satur)day[,\s]*)+)?",
                             text, re.I):
            price = int(m.group(1))
            days = None
            if m.group(2):
                days = sorted({DAY[d.lower()] for d in re.findall(r"(Sunday|Monday|Tuesday|Wednesday|Thursday|Friday|Saturday)", m.group(2), re.I)})
                days = days or None
            key = (meal, price)
            if key not in [(t["meal"], t["price"]) for t in tiers]:
                tiers.append({"meal": meal, "price": price, "days": days})
    return tiers

def parse_menu_blocks(soup):
    """Best-effort capture of the Spice menu text for human review / later decoding."""
    txt = soup.get_text("\n", strip=True)
    m = re.search(r"Miami Spice Menu(.*?)DISCLAIMER", txt, re.S)
    return m.group(1).strip()[:4000] if m else None

def scrape(slug, debug=False):
    url = BASE + slug + "/"
    html = get(url)
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text(" ", strip=True)
    if debug:
        Path(f"debug-{slug}.txt").write_text(text, encoding="utf-8")
    h1 = soup.find("h1")
    name = re.sub(r"\s*Miami Spice.*$", "", h1.get_text(strip=True)) if h1 else slug
    tiers = parse_tiers(text)
    return {"name": name, "srcSlug": slug, "srcUrl": url,
            "tiers": tiers, "menuText": parse_menu_blocks(soup)}

def norm(s):
    return re.sub(r"[^a-z0-9]", "", s.lower())

def merge(results):
    data = json.loads(DATA.read_text(encoding="utf-8"))
    decoded_names = {norm(r["name"]) for r in data["decoded"]}
    tiers_by_name = {norm(t["name"]): t for t in data["tiersOnly"]}
    roster_by_name = {norm(e["name"]): e for e in data["roster"]}
    added = updated = skipped = 0
    for r in results:
        k = norm(r["name"])
        if not r["tiers"]:
            print(f"  ! no tiers parsed for {r['name']} — skipped (run --debug)"); skipped += 1; continue
        if k in decoded_names:
            print(f"  = {r['name']} already decoded — menuText saved for cross-check")
        entry = tiers_by_name.get(k)
        if entry:
            entry.update({"tiers": r["tiers"], "srcUrl": r["srcUrl"], "menuText": r["menuText"]}); updated += 1
        else:
            e = roster_by_name.get(k)
            new = {"name": r["name"], "tiers": r["tiers"], "srcUrl": r["srcUrl"], "menuText": r["menuText"]}
            if e:
                new["name"] = e["name"]  # keep official roster name so the app can match & pull it
            else:
                print(f"  ? {r['name']} not on official roster — added anyway, verify manually")
            data["tiersOnly"].append(new); added += 1
    DATA.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"merged: {added} added, {updated} updated, {skipped} skipped -> {DATA}")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("slugs", nargs="*")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--debug", action="store_true")
    a = ap.parse_args()
    if a.list:
        for s in list_pages(): print(s)
        return
    slugs = a.slugs
    if a.all:
        slugs = list_pages()
        print(f"{len(slugs)} restaurant pages found")
    if not slugs:
        ap.print_help(); sys.exit(1)
    results = []
    for i, s in enumerate(slugs, 1):
        try:
            print(f"[{i}/{len(slugs)}] {s}")
            results.append(scrape(s, a.debug))
        except Exception as e:
            print(f"  ! {s}: {e}")
        time.sleep(2)
    merge(results)

if __name__ == "__main__":
    main()
