import unittest

from bs4 import BeautifulSoup

from apply_valuation_review import resolved_match
from fetch_spice import merge, parse_menu_pane, parse_schedule
from fetch_regular_menus import BULLA_BRUNCH_PDF, build_review, discover_menu_urls, html_candidates, normalized, parse_price, restore_decisions, saved_decisions, score_match


class OfficialListingParserTests(unittest.TestCase):
    def test_review_decision_overrides_confidence_gate(self):
        weak_match = {"confidence": 0.5, "effectiveValue": 18, "sourceUrl": "https://example.test/menu"}
        choice = {"matches": [weak_match], "decision": {"type": "accept", "match": weak_match}}

        self.assertEqual(resolved_match(choice, 0.8), weak_match)
        self.assertIsNone(resolved_match({"matches": [weak_match], "decision": None}, 0.8))
        self.assertIsNone(resolved_match({"matches": [weak_match], "decision": {"type": "unavailable"}}, 0.8))

    def test_review_decisions_survive_candidate_regeneration(self):
        decision = {"type": "manual", "match": {"effectiveValue": 21, "sourceUrl": "https://example.test/menu"}}
        old_review = {"restaurants": [{"name": "Example", "tiers": [{"meal": "dinner", "price": 50, "courses": [
            {"course": "Entrees", "choices": [{"spiceName": "Dish", "decision": decision}]}
        ]}]}]}
        regenerated = {"name": "Example", "tiers": [{"meal": "dinner", "price": 50, "courses": [
            {"course": "Entrees", "choices": [{"spiceName": "Dish", "matches": [], "decision": None}]}
        ]}]}

        restore_decisions(regenerated, saved_decisions(old_review))

        self.assertEqual(regenerated["tiers"][0]["courses"][0]["choices"][0]["decision"], decision)

    def test_schedule_maps_days_and_uses_none_when_no_days_are_active(self):
        spice = BeautifulSoup(
            """
            <div id="profile-spice"><table>
              <thead><tr><th></th><th>MON</th><th>TUE</th><th>WED</th><th>THU</th><th>FRI</th><th>SAT</th><th>SUN</th></tr></thead>
              <tbody>
                <tr><td>Lunch $40</td><td>√</td><td>√</td><td>√</td><td>√</td><td>√</td><td>-</td><td>-</td></tr>
                <tr><td>Dinner $50</td><td>-</td><td>-</td><td>-</td><td>-</td><td>-</td><td>-</td><td>-</td></tr>
              </tbody>
            </table></div>
            """,
            "html.parser",
        ).select_one("#profile-spice")

        self.assertEqual(
            parse_schedule(spice),
            [
                {"meal": "lunch", "price": 40, "days": [1, 2, 3, 4, 5]},
                {"meal": "dinner", "price": 50, "days": None},
            ],
        )

    def test_menu_keeps_descriptions_and_supplements(self):
        pane = BeautifulSoup(
            """
            <div id="lunch-40menu">
              <div class="ys-partner-details__tabs__container__info__temptation__group">
                <p class="ys-partner-details__tabs__container__info__temptation__group__name">Entrees</p>
                <p class="ys-partner-details__tabs__container__info__temptation__group__description">Choose one</p>
                <div class="ys-partner-details__tabs__container__info__temptation__group__items__item">
                  <p class="item-name">Hanger Steak (GF +$15)</p>
                  <p class="item-description">Frites and jus</p>
                </div>
              </div>
            </div>
            """,
            "html.parser",
        ).select_one("#lunch-40menu")

        self.assertEqual(
            parse_menu_pane(pane),
            [
                {
                    "course": "Entrees",
                    "instruction": "Choose one",
                    "choices": [
                        {"name": "Hanger Steak (GF +$15)", "description": "Frites and jus", "supplement": 15}
                    ],
                }
            ],
        )

    def test_menu_recovers_shifted_instruction_and_dessert_fields(self):
        pane = BeautifulSoup(
            """
            <div><div class="ys-partner-details__tabs__container__info__temptation__group">
              <p class="ys-partner-details__tabs__container__info__temptation__group__name">Desserts</p>
                            <p class="ys-partner-details__tabs__container__info__temptation__group__description"></p>
              <div class="ys-partner-details__tabs__container__info__temptation__group__items__item">
                <p class="item-name">Choose one of the following</p><p class="item-description">BOMBOLINI</p>
              </div>
              <div class="ys-partner-details__tabs__container__info__temptation__group__items__item">
                <p class="item-name">Italian donuts</p><p class="item-description">TIRAMISU</p>
              </div>
              <div class="ys-partner-details__tabs__container__info__temptation__group__items__item">
                <p class="item-name">Espresso-soaked ladyfingers</p>
              </div>
            </div></div>
            """,
            "html.parser",
        ).div

        self.assertEqual(
            parse_menu_pane(pane),
            [{
                "course": "Desserts",
                "choices": [
                    {"name": "BOMBOLINI", "description": "Italian donuts"},
                    {"name": "TIRAMISU", "description": "Espresso-soaked ladyfingers"},
                ],
                "instruction": "Choose one of the following",
            }],
        )

    def test_merge_demotes_decoded_restaurant_when_official_tier_changed(self):
        data = {
            "meta": {},
            "decoded": [{"name": "Example", "area": "Miami", "slug": "example/1", "tiers": [
                {"meal": "dinner", "price": 50, "days": [1], "menu": [{"c": "Entree", "d": [["Dish", 40]]}]}
            ]}],
            "tiersOnly": [],
            "roster": [],
        }
        result = {"name": "Example", "area": "Miami", "slug": "example/1", "srcUrl": "https://example.test", "capturedAt": "2026-08-03", "tiers": [
            {"meal": "dinner", "price": 65, "days": [0, 1, 2, 3, 4, 5, 6], "spiceMenu": []}
        ]}

        merge(data, [result], dry_run=True)

        self.assertEqual(data["decoded"], [])
        self.assertEqual(data["tiersOnly"], [result])

    def test_regular_menu_matching_handles_pdf_price_spacing(self):
        self.assertEqual(parse_price("17 .5"), 17.5)
        self.assertEqual(normalized("SALMÓN"), "salmon")
        self.assertGreater(score_match("HERILOOM TOMATO & BURRATA", "Heirloom Tomato & Burrata"), 0.8)

    def test_bulla_reviewed_price_keeps_exact_menu_source(self):
        entry = {
            "name": "Bulla Gastrobar Test",
            "slug": "bulla-test/1",
            "restaurantUrl": "https://bullagastrobar.com/menus/test/",
            "tiers": [{
                "meal": "brunch",
                "price": 40,
                "spiceMenu": [{"course": "Entrees", "choices": [{"name": "Huevos Benedictinos"}]}],
            }],
        }

        review = build_review(entry, [], [], [])

        self.assertEqual(
            review["tiers"][0]["courses"][0]["choices"][0]["matches"][0]["sourceUrl"],
            BULLA_BRUNCH_PDF,
        )

    def test_baires_current_html_is_parsed_and_holiday_menu_is_excluded(self):
        page_url = "https://www.bairesgrill.com/menu/brickell"
        html = """
            <div class="content-style-2">
              <div class="nombre-del-plato">ENTRAÑA</div>
              <div class="precio">$39.00</div>
              <div class="descripcion-del-plato">Certified Angus skirt steak</div>
            </div>
            <a href="/regular-menu.pdf">Dinner menu</a>
            <a href="/BG-BRK-HOLIDAY_MENU-13-NOV.pdf">Holiday menu</a>
        """

        self.assertEqual(html_candidates(page_url, html)[0]["name"], "ENTRAÑA")
        self.assertEqual(html_candidates(page_url, html)[0]["price"], 39)
        self.assertEqual(
            discover_menu_urls(page_url, html),
            ["https://www.bairesgrill.com/regular-menu.pdf"],
        )

    def test_application_json_menu_items_are_parsed(self):
        source_url = "https://www.getsauce.com/order/example/menu"
        html = """
            <script type="application/json">
              {"menu": [{"name": "Margherita", "description": "Tomato, mozzarella, basil", "price": 18}]}
            </script>
        """

        self.assertEqual(
            html_candidates(source_url, html),
            [{
                "name": "Margherita",
                "price": 18,
                "context": "Margherita Tomato, mozzarella, basil",
                "sourceUrl": source_url,
            }],
        )


if __name__ == "__main__":
    unittest.main()