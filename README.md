# Miami Spice 2026 — decoded

Unofficial value guide to Miami Spice Restaurant Months (Aug 1 – Sep 30, 2026).
Every prix fixe menu priced against what the same meal would cost a la carte,
plus the complete official participant roster with honest "limited data" tags
where details haven't been captured yet.

Live idea borrowed with admiration from dineout-lauderdale.

## What's in here

```text
index.html              The whole app (vanilla HTML/CSS/JS, no build step)
data/spice-data.json    All the data: decoded menus, verified tiers, full roster
scraper/fetch_spice.py  Collector for official tier/day/menu data
```

Three data levels, all in `spice-data.json`:

| Level      | What it has                              | How it renders                |
|------------|------------------------------------------|-------------------------------|
| `decoded`  | tiers, days, menu, a la carte worth      | Full card with value score    |
| `tiersOnly`| verified tier, days and captured menu    | Card tagged "value pending"   |
| `roster`   | name, neighborhood, official listing URL | Compact "limited data" card   |

## Run it locally (Windows)

The app loads its data with `fetch()`, so you need a local web server
(double-clicking index.html won't work). Python ships one:

1. Install Python from python.org if you don't have it (check "Add to PATH").
2. Open PowerShell in the repo folder and run:

   ```powershell
   py -m http.server 8000
   ```

3. Open <http://localhost:8000>

## Deploy to GitHub Pages

1. Create a new GitHub repo (e.g. `miami-spice-decoded`), then from the repo folder:

   ```powershell
   git init
   git add .
   git commit -m "Miami Spice 2026 decoded"
   git branch -M main
   git remote add origin https://github.com/YOURUSER/miami-spice-decoded.git
   git push -u origin main
   ```

   (Or drag the folder into GitHub Desktop and publish.)
2. On GitHub: Settings > Pages > Source: "Deploy from a branch" > Branch: `main`, folder `/ (root)` > Save.
3. Your site appears at `https://YOURUSER.github.io/miami-spice-decoded/` in a minute or two.

Updating data later is just: edit or scrape, commit, push. Pages redeploys automatically.

## Collect more data

```powershell
py -m pip install -r requirements.txt

# See records and slugs already known from the official roster
py scraper\fetch_spice.py --list

# Preview one official listing without changing the data file
py scraper\fetch_spice.py claudie-restaurant --dry-run

# Scrape specific restaurants (slug names from --list)
py scraper\fetch_spice.py delilah-miami hutong sugar

# Or enrich every tier-only and roster-only record (1s between downloads)
py scraper\fetch_spice.py --all
```

The collector reads the structured schedule and menu on each official GMCVB
listing. Roster entries with published tiers move into `tiersOnly`, including
their course choices, restaurant website, source URL and capture date. Downloads
are cached in `scraper/.cache/` to make retries fast; that directory is ignored
by Git and may contain HTML or PDFs. Existing decoded records are refreshed too:
official days replace stale days, obsolete tiers are removed, and newly published
tiers appear as value pending until they are priced.

Promoting a restaurant to `decoded` remains an editorial step: use the captured
restaurant website to find its current regular menu, add per-dish à la carte
prices in the existing decoded `menu` shape, and set `verified: true` only when
every price came from that restaurant's own current menu.

The regular-menu collector builds a source-backed review queue without publishing
uncertain matches:

```powershell
py scraper\fetch_regular_menus.py --domains northitalia.com bullagastrobar.com
```

It reads regular menu HTML, PDFs and structured application JSON, ignores links
clearly labeled as holiday or promotional menus, and records inaccessible menu
endpoints as review errors instead of silently substituting stale evidence.

This writes `data/valuation-review.json` with candidate prices, confidence,
source text, URLs and supplement-adjusted values. Once every choice for a named
restaurant has been reviewed, the guarded promoter requires complete coverage:

```powershell
py scraper\review_queue.py --open
```

The local reviewer opens at `http://127.0.0.1:8765/review.html`. It starts with
only ambiguous choices, shows candidate prices beside their source excerpts,
and saves accepted candidates, manual evidence, or explicit "no equivalent"
decisions directly to the review queue. Decisions survive later candidate
refreshes. The server binds only to the local machine.

```powershell
py scraper\apply_valuation_review.py "Bulla Gastrobar Aventura" --minimum-confidence 0.8 --dry-run
```

Remove `--dry-run` only after the review passes. Any missing or weak tier remains
value pending rather than receiving an estimated score.

Run the focused parser tests with:

```powershell
py -m unittest discover -s scraper -p "test_*.py" -v
```

## Data honesty rules

- `~` before a price = tier price is an estimate, not confirmed
- `days: null` = restaurant didn't publish days; the app keeps these in day
  filters and counts them separately rather than pretending to know
- grey dot = a la carte worth is benchmarked; green dot = verified from the
  restaurant's current menu
- roster names, neighborhoods and listing links come from the official GMCVB
  directory, captured 2026-08-02

Everything excludes drinks, tax and gratuity. Unaffiliated with the GMCVB or
any restaurant. Menus change without notice.
