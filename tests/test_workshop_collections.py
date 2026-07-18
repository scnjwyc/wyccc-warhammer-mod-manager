from __future__ import annotations

import io
import json
import unittest
from unittest.mock import patch

from backend.workshop_collections import (
    COLLECTION_DETAILS_ENDPOINT,
    fetch_workshop_collection,
    parse_workshop_collection_id,
)


class WorkshopCollectionTests(unittest.TestCase):
    def test_accepts_collection_id_and_standard_steam_url(self) -> None:
        self.assertEqual(parse_workshop_collection_id("123456"), "123456")
        self.assertEqual(
            parse_workshop_collection_id(
                "https://steamcommunity.com/sharedfiles/filedetails/?id=123456"
            ),
            "123456",
        )
        with self.assertRaisesRegex(ValueError, "合集链接"):
            parse_workshop_collection_id("https://steamcommunity.com/sharedfiles/filedetails/")

    def test_reads_children_in_collection_sort_order(self) -> None:
        payload = {
            "response": {
                "collectiondetails": [
                    {
                        "result": 1,
                        "publishedfileid": "900",
                        "children": [
                            {"publishedfileid": "456", "sortorder": 2},
                            {"publishedfileid": "123", "sortorder": 1},
                            {"publishedfileid": "123", "sortorder": 3},
                            {"publishedfileid": "invalid", "sortorder": 4},
                        ],
                    }
                ]
            }
        }
        class Response(io.BytesIO):
            def __enter__(self) -> "Response":
                return self

            def __exit__(self, *_args: object) -> None:
                return None

        response = Response(json.dumps(payload).encode("utf-8"))

        with patch("backend.workshop_collections.urllib.request.urlopen", return_value=response) as urlopen:
            collection = fetch_workshop_collection("900", app_id=1_142_710)

        request = urlopen.call_args.args[0]
        self.assertEqual(request.full_url, COLLECTION_DETAILS_ENDPOINT)
        self.assertIn(b"collectioncount=1", request.data)
        self.assertEqual(collection["collection_id"], "900")
        self.assertEqual(collection["title"], "")
        self.assertEqual(
            [item["workshop_id"] for item in collection["references"]],
            ["123", "456"],
        )


if __name__ == "__main__":
    unittest.main()
