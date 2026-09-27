"""Unit tests for the AI Product Hunter Automation backend.

Phase 4: mocked Decodo discovery-scraping tests. Phase 5: mocked coverage
for content parsing, response compaction, product extraction,
deduplication, local viral scoring, and discovery summary behavior. These
tests never call the live Decodo API — api.http is patched with a fake
client via unittest.mock, and a dummy auth token is set before api is
imported.
"""

import json
import math
import os
import unittest
from unittest import mock

os.environ.setdefault("DECODO_AUTH_TOKEN", "test-token")

import api


class HTTPError(Exception):
    pass


class Timeout(Exception):
    pass


class FakeResponse:
    def __init__(self, payload=None, invalid_json=False, status_code=200):
        self._payload = payload
        self._invalid_json = invalid_json
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise HTTPError(f"Error {self.status_code}")

    def json(self):
        if self._invalid_json:
            raise ValueError("Expecting value: line 1 column 1 (char 0)")
        return self._payload


class FakeHTTP:
    """Stand-in for the requests module; records calls, never hits network."""

    def __init__(self, responder=None):
        self.calls = []
        self.responder = responder or (lambda payload: FakeResponse({"results": ["ok"]}))

    def post(self, url, json=None, headers=None, timeout=None):
        self.calls.append(
            {"url": url, "payload": json, "headers": headers, "timeout": timeout}
        )
        result = self.responder(json)
        if isinstance(result, Exception):
            raise result
        return result


class BuildSourceUrlsTests(unittest.TestCase):
    def test_ten_ordered_sources(self):
        sources = api.build_source_urls("pet gadgets")
        self.assertEqual(len(sources), 10)
        names = [s["source"] for s in sources]
        self.assertEqual(names[:6], [f"Google Search {i}" for i in range(1, 7)])
        self.assertEqual(
            names[6:],
            ["Amazon Search", "Reddit Search", "TikTok Shop Search", "YouTube Search"],
        )
        for source in sources:
            self.assertIn("target", source["payload"])


class ScrapeWithDecodoPayloadTests(unittest.TestCase):
    def test_success_shape_and_direct_post(self):
        fake = FakeHTTP()
        payload = {"target": "google_search", "query": "viral pet gadgets"}
        with mock.patch.object(api, "http", fake):
            result = api.scrape_with_decodo_payload("Google Search 1", payload)
        self.assertEqual(
            result,
            {"source": "Google Search 1", "request": payload, "data": {"results": ["ok"]}},
        )
        call = fake.calls[0]
        # Payload posted directly as JSON, never wrapped in another "payload" key.
        self.assertEqual(call["payload"], payload)
        self.assertEqual(call["url"], api.DECODO_API_URL)
        self.assertEqual(call["headers"]["accept"], "application/json")
        self.assertEqual(call["headers"]["content-type"], "application/json")
        self.assertEqual(call["headers"]["authorization"], f"Basic {api.DECODO_AUTH_TOKEN}")
        self.assertEqual(call["timeout"], (10, api.DECODO_REQUEST_TIMEOUT))

    def test_non_2xx_becomes_error_entry(self):
        fake = FakeHTTP(lambda p: FakeResponse(status_code=500))
        with mock.patch.object(api, "http", fake):
            result = api.scrape_with_decodo_payload("Boom", {"target": "x"})
        self.assertEqual(result["source"], "Boom")
        self.assertIn("error", result)
        self.assertNotIn("data", result)

    def test_timeout_becomes_error_entry(self):
        fake = FakeHTTP(lambda p: Timeout("read timed out"))
        with mock.patch.object(api, "http", fake):
            result = api.scrape_with_decodo_payload("Slow", {"target": "x"})
        self.assertIn("timed out", result["error"])

    def test_invalid_json_becomes_error_entry(self):
        fake = FakeHTTP(lambda p: FakeResponse(invalid_json=True))
        with mock.patch.object(api, "http", fake):
            result = api.scrape_with_decodo_payload("BadJSON", {"target": "x"})
        self.assertIn("error", result)


class ScrapeWithDecodoTests(unittest.TestCase):
    def test_all_ten_sources_order_preserved_with_isolated_failure(self):
        def responder(payload):
            source = payload["_test_source"]
            if source == "Reddit Search":
                raise Timeout("read timed out")
            return FakeResponse({"source": source})

        fake = FakeHTTP(responder)

        def tagged_scrape(name, payload):
            tagged = dict(payload)
            tagged["_test_source"] = name
            return real_scrape(name, tagged)

        messages = []
        with mock.patch.object(api, "http", fake):
            real_scrape = api.scrape_with_decodo_payload
            with mock.patch.object(api, "scrape_with_decodo_payload", tagged_scrape):
                raw = api.scrape_with_decodo("pet gadgets", logger=messages.append)

        results = json.loads(raw)
        expected_names = [s["source"] for s in api.build_source_urls("pet gadgets")]
        self.assertEqual([r["source"] for r in results], expected_names)
        failed = [r["source"] for r in results if "error" in r]
        self.assertEqual(failed, ["Reddit Search"])
        self.assertTrue(any("Discovery started" in m for m in messages))
        self.assertTrue(
            any("Reddit Search" in m and "failed" in m.lower() for m in messages)
        )
        self.assertEqual(sum(1 for m in messages if "succeeded" in m.lower()), 9)

    def test_no_logger_still_returns_ten_entries(self):
        fake = FakeHTTP()
        with mock.patch.object(api, "http", fake):
            results = json.loads(api.scrape_with_decodo("gadgets"))
        self.assertEqual(len(results), 10)
        self.assertEqual(len(fake.calls), 10)
        self.assertTrue(all("data" in r for r in results))

    def test_worker_count_bounded(self):
        captured = {}
        real_executor = api.ThreadPoolExecutor

        class SpyExecutor(real_executor):
            def __init__(self, max_workers=None, **kwargs):
                captured["max_workers"] = max_workers
                super().__init__(max_workers=max_workers, **kwargs)

        fake = FakeHTTP()
        with mock.patch.object(api, "http", fake), mock.patch.object(
            api, "ThreadPoolExecutor", SpyExecutor
        ):
            with mock.patch.object(api, "DECODO_MAX_WORKERS", 5):
                api.scrape_with_decodo("gadgets")
                self.assertEqual(captured["max_workers"], 5)
            with mock.patch.object(api, "DECODO_MAX_WORKERS", 0):
                api.scrape_with_decodo("gadgets")
                self.assertEqual(captured["max_workers"], 1)
            with mock.patch.object(api, "DECODO_MAX_WORKERS", 999):
                api.scrape_with_decodo("gadgets")
                self.assertEqual(captured["max_workers"], 10)


# ---------------------------------------------------------------------------
# Phase 5: parsing, compaction, extraction, dedup, viral score, summaries
# ---------------------------------------------------------------------------

def _amazon_result(products, source="Amazon Search"):
    return {
        "source": source,
        "request": {"target": "amazon_search"},
        "data": {
            "status_code": 200,
            "parser": {"status": "success"},
            "content": json.dumps({"results": {"job": {"id": "j1"}, "results": {"products": products}}}),
        },
    }


class ContentParsingTests(unittest.TestCase):
    def test_json_string_is_parsed(self):
        parsed = api.parse_decodo_content('{"a": 1}')
        self.assertEqual(parsed, {"a": 1})

    def test_html_markdown_text_left_as_string(self):
        for text in ("<html><body>hi</body></html>", "# Markdown title\nplain text", "just words"):
            self.assertEqual(api.parse_decodo_content(text), text)

    def test_stringify_variants(self):
        self.assertEqual(api.stringify_decodo_content(None), "")
        self.assertEqual(api.stringify_decodo_content("abc"), "abc")
        self.assertIn('"a"', api.stringify_decodo_content({"a": 1}))

    def test_envelope_layout_dict_results_descends_to_record(self):
        content = {"results": {"results": {"products": [{"title": "X", "price": 9}]}}}
        parsed = api.get_parsed_results(content)
        # Descended past both dict envelopes to the actual product-ish record.
        self.assertEqual(parsed, {"products": [{"title": "X", "price": 9}]})

    def test_non_dict_results_returned_directly(self):
        content = {"results": [{"product_title": "A", "price": 3}]}
        parsed = api.get_parsed_results(content)
        self.assertIsInstance(parsed, list)

    def test_no_results_key_uses_content_itself(self):
        content = {"products": [{"title": "A", "price": 3}]}
        self.assertEqual(api.get_parsed_results(content), content)

    def test_envelope_never_treated_as_product(self):
        # The outer envelope alone has no title/signal; extraction must skip it.
        result = _amazon_result([{"title": "Real Product", "price": "11.99"}])
        products = api.extract_products([result])
        self.assertEqual([p["product"] for p in products], ["Real Product"])


class TrimDecodoResultTests(unittest.TestCase):
    def test_deep_copy_leaves_original_untouched(self):
        original = _amazon_result([{"title": "Widget", "price": 9.99, "junk": "x" * 100}])
        snapshot = json.dumps(original, sort_keys=True)
        trimmed = api.trim_decodo_result(original, max_content_chars=10)
        self.assertEqual(json.dumps(original, sort_keys=True), snapshot)
        self.assertIsNot(trimmed, original)

    def test_amazon_caps_at_25_and_keeps_useful_fields(self):
        products = [
            {
                "position": i,
                "title": f"P{i}",
                "price": 9.99,
                "currency": "USD",
                "rating": 4.5,
                "reviews": 100,
                "badges": ["Best Seller"],
                "asin": f"B0{i:08d}",
                "url": "/dp/B000000001",
                "image": "https://img.example/p.jpg",
                "huge_debug_blob": "y" * 500,
            }
            for i in range(40)
        ]
        trimmed = api.trim_decodo_result(_amazon_result(products), max_content_chars=3500)
        kept = trimmed["data"]["products"]
        self.assertEqual(len(kept), 25)
        self.assertNotIn("huge_debug_blob", kept[0])
        self.assertEqual(kept[0]["url"], "https://www.amazon.com/dp/B000000001")
        for key in ("position", "title", "price", "rating", "badges", "asin", "image"):
            self.assertIn(key, kept[0])

    def test_google_bounded_sections_preserved(self):
        organic = [{"title": f"o{i}", "link": f"https://e.com/{i}"} for i in range(30)]
        questions = [{"question": f"q{i}"} for i in range(20)]
        shopping = {"shopping_results": [{"title": f"s{i}", "price": i} for i in range(40)]}
        result = {
            "source": "Google Search 1",
            "data": {
                "content": {
                    "query": "viral pet gadgets",
                    "page": 1,
                    "status": "finished",
                    "ai_overview": [{"snippet": f"a{i}"} for i in range(6)],
                    "organic": organic,
                    "related_questions": questions,
                    "shopping": shopping,
                }
            },
        }
        trimmed = api.trim_decodo_result(result, max_content_chars=500)
        data = trimmed["data"]
        self.assertEqual(data["query"], "viral pet gadgets")
        self.assertEqual(data["page"], 1)
        self.assertEqual(data["status"], "finished")
        self.assertEqual(len(data["ai_overview"]), 3)
        self.assertEqual(len(data["organic"]), 10)
        self.assertEqual(len(data["related_questions"]), 10)
        # Object-valued section preserved without blind flattening, capped at 25.
        self.assertIsInstance(data["shopping"], dict)
        self.assertEqual(len(data["shopping"]["shopping_results"]), 25)

    def test_long_unstructured_text_is_truncated_everywhere(self):
        huge_html = "<html>" + "z" * 9999 + "</html>"
        result = {
            "source": "YouTube Search",
            "data": {"content": {"description": huge_html}},
        }
        trimmed = api.trim_decodo_result(result, max_content_chars=500)
        description = trimmed["data"]["description"]
        self.assertLess(len(description), 700)
        self.assertTrue(description.endswith("...[truncated]"))

    def test_structured_json_stays_structured(self):
        products = [{"title": "Gadget", "price": 12.5}] * 3
        trimmed = api.trim_decodo_result(_amazon_result(products), max_content_chars=3500)
        self.assertIsInstance(trimmed["data"], dict)
        self.assertEqual(trimmed["data"]["products"][0]["price"], 12.5)

    def test_error_entries_pass_through(self):
        entry = {"source": "Reddit Search", "request": {}, "error": "timeout"}
        trimmed = api.trim_decodo_result(entry)
        self.assertEqual(trimmed["error"], "timeout")
        self.assertNotIn("data", trimmed)

    def test_discovery_scrape_trims_before_returning(self):
        html = "<html>" + "a" * 50000 + "</html>"

        def responder(payload):
            return FakeResponse({"status_code": 200, "content": html})

        fake = FakeHTTP(responder)
        with mock.patch.object(api, "http", fake):
            results = json.loads(api.scrape_with_decodo("pet gadgets"))
        successful = [r for r in results if "data" in r]
        self.assertTrue(successful)
        # One unstructured string per entry, capped at the 12k discovery limit.
        for r in successful:
            self.assertIsInstance(r["data"], str)
            self.assertLessEqual(len(r["data"]), 12015)


class ExtractProductsTests(unittest.TestCase):
    def test_extracts_and_normalizes_records(self):
        products = [
            {
                "product_title": "Self-Cleaning Pet Brush",
                "current_price": "$18.99",
                "currency": "USD",
                "relative_url": "/dp/B0ABCDEFGH",
                "images": [{"url": "https://img.example/brush.jpg"}],
                "rating": 4.6,
                "reviews": 12000,
                "badges": ["Amazon's Choice"],
                "asin": "B0ABCDEFGH",
            },
            {"title": "Search suggestions", "name": ""},  # navigation noise: no signal
        ]
        extracted = api.extract_products([_amazon_result(products)])
        self.assertEqual(len(extracted), 1)
        product = extracted[0]
        self.assertEqual(product["product"], "Self-Cleaning Pet Brush")
        self.assertEqual(product["source"], ["Amazon Search"])
        self.assertEqual(product["price"], 18.99)
        self.assertEqual(product["currency"], "USD")
        self.assertEqual(product["url"], "https://www.amazon.com/dp/B0ABCDEFGH")
        self.assertEqual(product["image"], "https://img.example/brush.jpg")
        self.assertIsInstance(product["evidence"], list)
        self.assertIsInstance(product["viral_score"], int)

    def test_title_only_records_never_emitted(self):
        records = [{"title": "All results"}, {"name": "Next page →"}, {"product_name": "   "}]
        self.assertEqual(api.extract_products([_amazon_result(records)]), [])

    def test_signal_required_but_sales_counts(self):
        records = [{"title": "Trending Kitten Ball", "bought_in_past_month": "2,000+ bought"}]
        extracted = api.extract_products([_amazon_result(records)])
        self.assertEqual(len(extracted), 1)
        self.assertEqual(extracted[0]["sales"], 2000.0)

    def test_deduplication_merges_sources_evidence_and_fills_gaps(self):
        amazon = _amazon_result(
            [{"title": "LED Dog Collar!", "price": None, "rating": 4.4}]
        )
        google = {
            "source": "Google Search 1",
            "data": {
                "content": {
                    "organic": [
                        {"name": "led dog collar", "price": "21.50", "link": "https://shop.example/collar", "thumbnail": "https://img.example/collar.png"}
                    ]
                }
            },
        }
        extracted = api.extract_products([amazon, google])
        self.assertEqual(len(extracted), 1)
        merged = extracted[0]
        self.assertEqual(sorted(merged["source"]), sorted(["Amazon Search", "Google Search 1"]))
        self.assertEqual(merged["price"], 21.5)  # filled from later record
        self.assertEqual(merged["url"], "https://shop.example/collar")
        self.assertEqual(merged["image"], "https://img.example/collar.png")
        self.assertTrue(len(merged["evidence"]) >= 1)

    def test_limit_caps_unique_candidates(self):
        products = [{"title": f"Item {i}", "price": 10 + i} for i in range(60)]
        extracted = api.extract_products([_amazon_result(products)], limit=25)
        self.assertEqual(len(extracted), 25)

    def test_sorted_by_score_descending(self):
        products = [
            {"title": "Bare Thing", "price": 200},  # weak: base only
            {"title": "Star Thing", "price": 20, "rating": 5.0, "reviews": 100000, "image": "https://i/x.jpg", "url": "https://a.com/dp/1", "badges": ["Best Seller"]},
        ]
        extracted = api.extract_products([_amazon_result(products)])
        self.assertEqual(extracted[0]["product"], "Star Thing")
        scores = [p["viral_score"] for p in extracted]
        self.assertEqual(scores, sorted(scores, reverse=True))


class ViralScoreTests(unittest.TestCase):
    def _score(self, **overrides):
        product = {
            "price": None, "rating": None, "reviews": None, "sales": None,
            "image": None, "url": None, "evidence": [],
        }
        product.update(overrides)
        return api._compute_viral_score(product)

    def test_base_score(self):
        self.assertEqual(self._score(), 35)

    def test_price_window_inclusive_bounds(self):
        self.assertEqual(self._score(price=5), 47)
        self.assertEqual(self._score(price=50), 47)
        self.assertEqual(self._score(price=4.99), 35)
        self.assertEqual(self._score(price=50.01), 35)

    def test_rating_component(self):
        self.assertEqual(self._score(rating=4.0), 35 + round(4.0 * 3))
        self.assertEqual(self._score(rating=5.0), 35 + 15)  # capped at 15

    def test_volume_component_log_scale(self):
        self.assertEqual(self._score(reviews=100), 35 + round(math.log10(100) * 5))
        self.assertEqual(self._score(sales=100000000), 35 + 18)  # capped at 18

    def test_image_and_url_points(self):
        self.assertEqual(self._score(image="i", url="u"), 45)

    def test_badge_evidence_points(self):
        self.assertEqual(self._score(evidence=["Pet Gadget", "Best Seller"]), 45)
        self.assertEqual(self._score(evidence=["Amazon's Choice"]), 45)
        self.assertEqual(self._score(evidence=["New Arrival"]), 35)

    def test_capped_at_100(self):
        score = self._score(
            price=25, rating=5.0, reviews=10**12, image="i", url="u",
            evidence=["Best Seller", "Amazon's Choice"],
        )
        self.assertEqual(score, 100)


class SummarizeDecodoResultTests(unittest.TestCase):
    def test_success_row_shape(self):
        result = _amazon_result([
            {"title": "Widget A", "price": 9.99},
            {"title": "Widget B", "price": 12.5},
        ])
        summary = api.summarize_decodo_result(result)
        self.assertEqual(summary["source"], "Amazon Search")
        self.assertEqual(summary["error"], "")
        self.assertEqual(summary["product_count"], 2)
        self.assertEqual(summary["response_count"], 2)
        self.assertEqual(summary["status_code"], 200)
        self.assertEqual(summary["parser_status"], "success")
        self.assertGreater(summary["content_chars"], 0)
        self.assertIn("ok", summary["status"])
        self.assertIn("http:200", summary["status"])
        self.assertIn("products:2", summary["status"])

    def test_error_row(self):
        summary = api.summarize_decodo_result({"source": "Reddit Search", "error": "read timed out"})
        self.assertEqual(summary["source"], "Reddit Search")
        self.assertIn("timed out", summary["error"])
        self.assertEqual(summary["product_count"], 0)
        self.assertTrue(summary["status"].startswith("error"))

    def test_one_row_per_source_via_hunt(self):
        fake = FakeHTTP()
        with mock.patch.object(api, "http", fake):
            payload = api.hunt(api.HuntRequest(niche="pet gadgets"))
        self.assertEqual(len(payload["discovery_summary"]), 10)
        self.assertEqual(
            [row["source"] for row in payload["discovery_summary"]],
            [s["source"] for s in api.build_source_urls("pet gadgets")],
        )
        # Compact debug data, not raw responses; supplier/final fields empty.
        self.assertEqual(payload["final_products"], [])
        self.assertEqual(payload["supplier_data"], [])
        self.assertEqual(payload["supplier_summary"], {})
        self.assertIsInstance(payload["initial_products"], list)


if __name__ == "__main__":
    unittest.main()
