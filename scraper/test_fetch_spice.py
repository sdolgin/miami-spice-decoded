import unittest

from bs4 import BeautifulSoup

from fetch_spice import parse_menu_pane, parse_schedule


class OfficialListingParserTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()