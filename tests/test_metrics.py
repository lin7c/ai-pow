from decimal import localcontext
import unittest

import ai_pow


def event(kind, data):
    return {"type": kind, "data": data}


class MetricTests(unittest.TestCase):
    def test_stream_chunking_does_not_inflate_estimate(self):
        whole = ai_pow.summary([event("assistant.visible", ai_pow.text_meta("abcdefgh"))])
        chunks = ai_pow.summary(event("assistant.visible", ai_pow.text_meta(c)) for c in "abcdefgh")
        self.assertEqual(whole["visible_ai"]["tokens_estimated"], 2)
        self.assertEqual(chunks["visible_ai"]["tokens_estimated"], 2)
        self.assertEqual(chunks["visible_ai"]["events"], 8)

    def test_missing_usage_is_null_with_separate_known_subtotal(self):
        rows = [event("model.usage", {"model": "test", "measurement": "provider_reported", "input_tokens": 10}),
                event("model.usage", {"model": "test", "measurement": "provider_reported", "output_tokens": 5})]
        totals = ai_pow.summary(rows)
        model = totals["models"]["test/provider_reported"]
        self.assertIsNone(model["input_tokens"])
        self.assertIsNone(model["output_tokens"])
        self.assertEqual(model["known_token_subtotals"]["input_tokens"], 10)
        self.assertEqual(model["missing_field_calls"]["input_tokens"], 1)
        self.assertFalse(totals["reference_cost_complete_for_observed_calls"])

    def test_missing_text_counts_are_explicit(self):
        result = ai_pow.summary([event("human.message", {})])["human"]
        self.assertEqual(result["unknown_token_events"], 1)
        self.assertFalse(result["tokens_complete"])
        self.assertIsNone(result["attention_seconds"])

    def test_costs_do_not_hide_estimated_basis(self):
        rows = [event("model.usage", {"model": "test", "measurement": "provider_reported", "reference_usd": "1.23"}),
                event("model.usage", {"model": "test", "measurement": "estimated", "reference_usd": "2.34"}),
                event("model.usage", {"model": "test", "measurement": "estimated"})]
        totals = ai_pow.summary(rows)
        self.assertEqual(totals["reference_usd_by_measurement"]["provider_reported"]["known_subtotal"], "1.23")
        self.assertEqual(totals["reference_usd_by_measurement"]["estimated"]["known_subtotal"], "2.34")
        self.assertFalse(totals["reference_usd_by_measurement"]["estimated"]["complete_for_observed_calls"])
        self.assertFalse(totals["ranking_eligible"])
        self.assertIsNone(totals["overall_score"])

    def test_legacy_reducer_remains_available(self):
        rows = [event("assistant.visible", ai_pow.text_meta(c)) for c in "abcd"]
        self.assertEqual(ai_pow.summary(rows, "observed-v1")["visible_ai"]["tokens_estimated"], 4)
        self.assertEqual(ai_pow.summary(rows)["visible_ai"]["tokens_estimated"], 1)
        with self.assertRaises(ValueError):
            ai_pow.summary([], "unrecognized")

    def test_byte_estimate_cannot_be_mislabeled(self):
        with self.assertRaises(ValueError):
            ai_pow.validate_event("human.message", {"bytes": 4, "tokens": 100, "token_method": "utf8-bytes/4-estimate"})

    def test_price_is_independent_of_callers_decimal_precision(self):
        price = {"model": "test", "source_url": "https://example.invalid/pricing", "effective_date": "2026-09-12",
                 "input_per_million": "1.23456789", "cached_input_per_million": "0.1",
                 "cache_write_per_million": "2", "output_per_million": "5"}
        usage = {"model": "test", "input_tokens": 12345, "cached_input_tokens": 0,
                 "cache_write_tokens": 0, "output_tokens": 0}
        with localcontext() as ctx:
            ctx.prec = 3
            a = ai_pow.price_usage(usage, price)["reference_usd"]
        with localcontext() as ctx:
            ctx.prec = 50
            b = ai_pow.price_usage(usage, price)["reference_usd"]
        self.assertEqual(a, b)
