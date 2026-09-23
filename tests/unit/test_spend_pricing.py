import pytest

from shugo.spend.pricing import Price, PriceTable, cost_of_usage, default_prices

HAIKU = Price(input=1.0, output=5.0, cache_write_5m=1.25, cache_write_1h=2.0, cache_read=0.1)


def test_basic_input_output_cost():
    assert cost_of_usage(HAIKU, {"input_tokens": 1_000_000, "output_tokens": 200_000}) == pytest.approx(2.0)


def test_cache_tokens_use_their_own_rates():
    usage = {
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_creation_input_tokens": 3_000_000,
        "cache_creation": {"ephemeral_5m_input_tokens": 1_000_000, "ephemeral_1h_input_tokens": 2_000_000},
        "cache_read_input_tokens": 10_000_000,
    }
    # 1M * 1.25 + 2M * 2.0 + 10M * 0.1
    assert cost_of_usage(HAIKU, usage) == pytest.approx(1.25 + 4.0 + 1.0)


def test_cache_creation_without_breakdown_is_priced_as_5m():
    usage = {"cache_creation_input_tokens": 1_000_000}
    assert cost_of_usage(HAIKU, usage) == pytest.approx(1.25)


def test_missing_and_null_fields_count_as_zero():
    assert cost_of_usage(HAIKU, {"input_tokens": None}) == 0.0


def test_lookup_prefers_longest_prefix_and_handles_dated_ids():
    table = PriceTable(default_prices())
    assert table.lookup("claude-opus-5-5").input == 4.0  # not claude-opus-5 ($5)
    assert table.lookup("claude-opus-5").input == 5.0
    assert table.lookup("claude-haiku-4-5-20251001").input == 1.0
    assert table.lookup("gpt-6-sol") is None


def test_published_rates_in_default_table():
    p = default_prices()
    assert (p["claude-opus-5-5"].input, p["claude-opus-5-5"].output, p["claude-opus-5-5"].cache_read) == (4.0, 20.0, 0.20)
    assert (p["claude-haiku-4-5"].input, p["claude-haiku-4-5"].output) == (1.0, 5.0)
    assert p["claude-fable-5-1"].cache_read == 0.25


def test_input_estimate_scales_with_body_size():
    table = PriceTable({"m": HAIKU})
    assert table.estimate_input_cost(HAIKU, b"x" * 4_000_000) == pytest.approx(1.0)  # ~1M tokens
