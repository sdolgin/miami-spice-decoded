# Miami Spice 2026 — decoded

Unofficial value guide to Miami Spice Restaurant Months (Aug 1 – Sep 30, 2026).
Every prix fixe menu priced against what the same meal would cost a la carte,
plus the complete official participant roster with honest "limited data" tags
where details haven't been captured yet.

Live idea borrowed with admiration from dineout-lauderdale.

## What's in here

```
index.html              The whole app (vanilla HTML/CSS/JS, no build step)
data/spice-data.json    All the data: decoded menus, verified tiers, full roster
scraper/fetch_spice.py  Collector that pulls verified tier/day/menu data
```

Three data levels, all in `spice-data.json`:

| Level      | What it has                              | How it renders                |
|------------|------------------------------------------|-------------------------------|
| `decoded`  | tiers, days, menu, a la carte worth      | Full card with value score    |
| `tiersOnly`| verified tier price + days, no worth     | Card tagged "menu pending"    |
| `roster`   | name, neighborhood, official listing URL | Compact "limited data" card   |

## Run it locally (Windows)

The app loads its data with `fetch()`, so you need a local web server
(double-clicking index.html won't work). Python ships one:

1. Install Python from python.org if you don't have it (check "Add to PATH").
2. Open PowerShell in the repo folder and run:
   ```powershell
   py -m http.server 8000
   ```
3. Open http://localhost:8000

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
py -m pip install requests beautifulsoup4

# See which restaurant pages the source publishes
py scraper\fetch_spice.py --list

# Scrape specific restaurants (slug names from --list)
py scraper\fetch_spice.py delilah-miami hutong sugar

# Or everything it can find (sleeps 2s between requests, takes a while)
py scraper\fetch_spice.py --all
```

Scraped entries land in `tiersOnly` with verified tier prices and days plus the
raw Spice menu text saved in `menuText` for review. Promoting a restaurant to
`decoded` is a manual step: look up its regular a la carte prices, add a
`menu` array with per-dish worth (copy the shape of any decoded entry), and
set `verified: true` once every price came off the restaurant's own menu.

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
