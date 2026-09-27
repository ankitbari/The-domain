"""Unit tests for the AI Product Hunter Automation backend.

Phase 4: mocked Decodo discovery-scraping tests. These tests never call the
live Decodo API — api.http is patched with a fake client via unittest.mock,
and a dummy auth token is set before api is imported.
"""

import json
import os
import unittest
from unittest import mock

os.environ.setdefault("DECODO_AUTH_TOKEN", "dummy-test-token")

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


if __name__ == "__main__":
    unittest.main()
