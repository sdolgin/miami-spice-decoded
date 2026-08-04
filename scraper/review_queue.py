"""Serve the valuation review UI and save human decisions locally.

Run from the repository root:
    python scraper/review_queue.py
"""

import argparse
import json
import math
import webbrowser
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parent.parent
REVIEW = ROOT / "data" / "valuation-review.json"


def load_review():
    return json.loads(REVIEW.read_text(encoding="utf-8"))


def find_choice(review, key):
    restaurant = next((item for item in review["restaurants"] if item["name"] == key.get("restaurant")), None)
    if not restaurant:
        raise ValueError("restaurant not found")
    tier = next((item for item in restaurant.get("tiers", []) if item["meal"] == key.get("meal") and item["price"] == key.get("price")), None)
    if not tier:
        raise ValueError("tier not found")
    course = next((item for item in tier["courses"] if item["course"] == key.get("course")), None)
    if not course:
        raise ValueError("course not found")
    choice = next((item for item in course["choices"] if item["spiceName"] == key.get("spiceName")), None)
    if not choice:
        raise ValueError("choice not found")
    return choice


def valid_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def valid_source_url(value):
    parsed = urlparse(value) if isinstance(value, str) else None
    return bool(parsed and parsed.scheme in {"http", "https"} and parsed.netloc)


def decision_from_request(choice, request):
    if request is None:
        return None
    decision_type = request.get("type")
    if decision_type == "accept":
        match_index = request.get("matchIndex")
        if not isinstance(match_index, int) or isinstance(match_index, bool) or not 0 <= match_index < len(choice["matches"]):
            raise ValueError("candidate not found")
        return {"type": "accept", "match": choice["matches"][match_index]}
    if decision_type == "manual":
        name = str(request.get("regularName", "")).strip()
        source_url = str(request.get("sourceUrl", "")).strip()
        source_text = str(request.get("sourceText", "")).strip()
        price = request.get("regularPrice")
        supplement = request.get("supplement", 0)
        if not name or not valid_number(price) or price <= 0:
            raise ValueError("manual evidence requires a dish name and positive price")
        if not valid_number(supplement) or supplement < 0 or supplement > price:
            raise ValueError("supplement must be between zero and the regular price")
        if not valid_source_url(source_url):
            raise ValueError("manual evidence requires an http(s) source URL")
        match = {
            "regularName": name,
            "regularPrice": price,
            "supplement": supplement,
            "effectiveValue": price - supplement,
            "confidence": 1,
            "sourceUrl": source_url,
            "sourceText": source_text or f"{name} {price:g}",
            "reviewed": True,
        }
        return {"type": "manual", "match": match}
    if decision_type == "unavailable":
        return {"type": "unavailable", "note": str(request.get("note", "")).strip()}
    raise ValueError("unsupported decision type")


def save_decision(key, request):
    review = load_review()
    choice = find_choice(review, key)
    choice["decision"] = decision_from_request(choice, request)
    temporary = REVIEW.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(review, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(REVIEW)
    return choice["decision"]


class ReviewHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def send_json(self, value, status=200):
        body = json.dumps(value, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/api/review":
            try:
                self.send_json(load_review())
            except (OSError, json.JSONDecodeError) as error:
                self.send_json({"error": str(error)}, 500)
            return
        super().do_GET()

    def do_POST(self):
        if self.path != "/api/decision":
            self.send_json({"error": "not found"}, 404)
            return
        try:
            length = int(self.headers.get("Content-Length", 0))
            if length <= 0 or length > 100_000:
                raise ValueError("invalid request size")
            payload = json.loads(self.rfile.read(length))
            decision = save_decision(payload.get("key", {}), payload.get("decision"))
            self.send_json({"decision": decision})
        except (OSError, json.JSONDecodeError, ValueError, TypeError) as error:
            self.send_json({"error": str(error)}, 400)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--open", action="store_true", help="open the review UI in the default browser")
    args = parser.parse_args()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), ReviewHandler)
    url = f"http://127.0.0.1:{server.server_port}/review.html"
    print(f"Review queue: {url}")
    if args.open:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()