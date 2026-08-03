"""Promote complete, high-confidence valuation reviews into decoded data."""

import argparse
import json
import re
import unicodedata
from datetime import date
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data" / "spice-data.json"
REVIEW = ROOT / "data" / "valuation-review.json"


def normalized(value):
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]", "", value.lower())


def tier_from_review(source_tier, review_tier, minimum_confidence):
    courses = []
    sources = set()
    for course in review_tier["courses"]:
        dishes = []
        for choice in course["choices"]:
            if not choice["matches"] or choice["matches"][0]["confidence"] < minimum_confidence:
                return None
            match = choice["matches"][0]
            dishes.append([choice["spiceName"], match["effectiveValue"]])
            sources.add(match["sourceUrl"])
        courses.append({"c": course["course"], "d": dishes})
    return {
        "meal": source_tier["meal"],
        "price": source_tier["price"],
        "days": source_tier["days"],
        "verified": True,
        "valuationStatus": "reviewed",
        "valuedAt": date.today().isoformat(),
        "valuationSources": sorted(sources),
        "menu": courses,
        "spiceMenu": source_tier.get("spiceMenu", []),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("names", nargs="+", help="restaurant names to promote")
    parser.add_argument("--minimum-confidence", type=float, default=0.8)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    data = json.loads(DATA.read_text(encoding="utf-8"))
    reviews = json.loads(REVIEW.read_text(encoding="utf-8"))["restaurants"]
    review_by_name = {normalized(entry["name"]): entry for entry in reviews}
    tier_by_name = {normalized(entry["name"]): entry for entry in data["tiersOnly"]}
    wanted = {normalized(name) for name in args.names}
    promoted = []

    for key in wanted:
        source = tier_by_name.get(key)
        review = review_by_name.get(key)
        if not source or not review:
            print(f"! {key}: missing tier-only data or review")
            continue
        review_tiers = {(tier["meal"], tier["price"]): tier for tier in review["tiers"]}
        valued_tiers = []
        for source_tier in source["tiers"]:
            review_tier = review_tiers.get((source_tier["meal"], source_tier["price"]))
            valued = tier_from_review(source_tier, review_tier, args.minimum_confidence) if review_tier else None
            if valued:
                valued_tiers.append(valued)
            else:
                print(f"! {source['name']} {source_tier['meal']} ${source_tier['price']}: incomplete or below confidence")
        if len(valued_tiers) != len(source["tiers"]):
            continue
        promoted.append({
            "name": source["name"],
            "area": source["area"],
            "cuisine": "Spanish tapas" if "Bulla Gastrobar" in source["name"] else "Restaurant",
            "slug": source["slug"],
            "srcUrl": source["srcUrl"],
            "restaurantUrl": source.get("restaurantUrl"),
            "capturedAt": source.get("capturedAt"),
            "tiers": valued_tiers,
        })

    print(f"{'would promote' if args.dry_run else 'promoting'} {len(promoted)} restaurant(s), {sum(len(x['tiers']) for x in promoted)} tier(s)")
    if args.dry_run:
        return
    promoted_keys = {normalized(entry["name"]) for entry in promoted}
    data["tiersOnly"] = [entry for entry in data["tiersOnly"] if normalized(entry["name"]) not in promoted_keys]
    data["decoded"].extend(promoted)
    temporary = DATA.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(DATA)


if __name__ == "__main__":
    main()