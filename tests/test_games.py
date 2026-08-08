from __future__ import annotations

import unittest

from backend.games import game_definitions, get_game_definition


class SupportedGamesTests(unittest.TestCase):
    def test_registers_every_total_war_workshop_game(self) -> None:
        definitions = {game.id: game for game in game_definitions()}

        self.assertEqual(
            {game_id: game.app_id for game_id, game in definitions.items()},
            {
                "warhammer3": "1142710",
                "warhammer2": "594570",
                "warhammer": "364360",
                "three_kingdoms": "779340",
                "pharaoh_dynasties": "2951630",
                "pharaoh": "1937780",
                "troy": "1099410",
                "thrones_of_britannia": "712100",
                "attila": "325610",
                "rome2": "214950",
                "shogun2": "34330",
                "rome_remastered": "885970",
            },
        )

    def test_only_warhammer_three_enables_game_data_tools(self) -> None:
        definitions = game_definitions()

        self.assertEqual(
            [game.id for game in definitions if game.supports_game_data_modification],
            ["warhammer3"],
        )
        self.assertEqual(
            [game.id for game in definitions if game.supports_official_profile_import],
            ["warhammer3"],
        )
        self.assertEqual(
            [game.id for game in definitions if game.supports_unit_data_modification],
            ["warhammer3", "three_kingdoms"],
        )
        self.assertEqual(get_game_definition("shogun2").mod_list_encoding, "utf-16le")
        rome = get_game_definition("rome_remastered")
        self.assertEqual(rome.mod_format, "feral_directory")
        self.assertEqual(rome.data_relative_path, "Contents/Resources/Data/data")
        self.assertFalse(rome.uses_mod_list)
        self.assertFalse(rome.supports_save_games)
