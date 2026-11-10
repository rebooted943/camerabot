"""Grok bot scope: Vinted/OLX only, Fujifilm bodies and Fuji-mount lenses."""

import asyncio

from arbitrage_sniper.grok_bot import (
    ALLOWED_PROVIDERS,
    SEARCH_TOOL,
    SYSTEM_PROMPT,
    clamp_providers,
    execute_tool,
    is_fuji_listing,
    query_in_scope,
    search_listings,
)
from arbitrage_sniper.models import Item


def _item(title: str, price: float = 400.0, platform: str = "vinted", currency: str = "EUR") -> Item:
    return Item(
        id=title,
        title=title,
        price=price,
        link=f"https://example.test/{platform}/{title.replace(' ', '-')}",
        platform=platform,
        currency=currency,
    )


def test_prompt_and_tool_stay_on_vinted_olx():
    assert "vinted" in SYSTEM_PROMPT and "olx" in SYSTEM_PROMPT
    assert "terze parti" in SYSTEM_PROMPT
    enum = SEARCH_TOOL["parameters"]["properties"]["providers"]["items"]["enum"]
    assert enum == ["vinted", "olx"]
    assert ALLOWED_PROVIDERS == ("vinted", "olx")


def test_query_scope():
    assert query_in_scope("Fujifilm X-T5")
    assert query_in_scope("Fuji GFX 50S")
    assert query_in_scope("Viltrox 27mm Fuji")
    assert query_in_scope("Sigma 18-50 Fuji X")
    assert query_in_scope("Voigtländer 27mm Fuji")
    assert not query_in_scope("Sony A7 III")
    assert not query_in_scope("Sigma 24-70 Sony")
    assert not query_in_scope("Viltrox 27mm")
    assert not query_in_scope("")


def test_listing_scope():
    assert is_fuji_listing("Fujifilm X-T5 body")
    assert is_fuji_listing("Fuji XT4 mirrorless")
    assert is_fuji_listing("Fujifilm X-T50 black")
    assert is_fuji_listing("Fujifilm X-H2S")
    assert is_fuji_listing("Fujifilm GFX 50S")
    assert is_fuji_listing("Fujifilm X100V")
    assert is_fuji_listing("Fujifilm XF 35mm f2")
    assert is_fuji_listing("Fujinon GF 45mm")
    assert is_fuji_listing("Viltrox AF 27mm F1.2 XF Fuji X")
    assert is_fuji_listing("Sigma 18-50mm f2.8 DC DN Fuji X Mount")
    assert is_fuji_listing("TTArtisan 27mm f2.8 Fuji")
    assert not is_fuji_listing("Fujifilm X-T5 battery")
    assert not is_fuji_listing("Fujifilm X-T4 battery grip")
    assert not is_fuji_listing("adattatore Canon EF Fuji X")
    assert not is_fuji_listing("Sigma 24-70 Sony E")
    assert not is_fuji_listing("Canon EF 50mm for Fuji")
    assert not is_fuji_listing("Sony A7 III")


def test_search_rejects_other_brands_without_scraping():
    called = []

    async def searcher(provider, query):
        called.append((provider, query))
        return [_item("Sony A7 III")]

    result = asyncio.run(search_listings("Sony A7 III", searcher=searcher))
    assert result["items"] == []
    assert "error" in result
    assert called == []


def test_search_keeps_only_the_asked_body_and_providers():
    async def searcher(provider, query):
        assert provider == "vinted"
        return [
            _item("Fuji XT5 body", price=700, platform=provider),
            _item("Fujifilm X-T4 body", price=500, platform=provider),
            _item("Fujifilm X-T50", price=900, platform=provider),
            _item("Fujifilm X-T5 battery", price=40, platform=provider),
            _item("Fuji XT5 kit", price=750, platform=provider),
        ]

    result = asyncio.run(
        search_listings(
            "Fujifilm X-T5",
            providers=["subito", "vinted", "facebook"],
            limit=99,
            searcher=searcher,
        )
    )
    assert result["providers"] == ["vinted"]
    titles = [row["title"] for row in result["items"]]
    assert titles == ["Fuji XT5 body", "Fuji XT5 kit"]
    assert result["items"][0]["price_eur"] == 700


def test_third_party_lens_must_match_brand_and_focal():
    async def searcher(provider, query):
        return [
            _item("Viltrox 27mm f1.2 Fuji X", price=180, platform=provider),
            _item("Viltrox 13mm Fuji X", price=220, platform=provider),
            _item("Sigma 18-50mm Fuji X", price=300, platform=provider),
            _item("Viltrox 27mm Sony E", price=150, platform=provider),
        ]

    result = asyncio.run(
        search_listings("Viltrox 27mm Fuji", providers=["olx"], searcher=searcher)
    )
    assert result["providers"] == ["olx"]
    assert [row["title"] for row in result["items"]] == ["Viltrox 27mm f1.2 Fuji X"]


def test_zoom_query_requires_both_ends():
    async def searcher(provider, query):
        return [
            _item("Sigma 18-50mm f2.8 Fuji X", price=320),
            _item("Sigma 56mm Fuji X", price=200),
        ]

    result = asyncio.run(search_listings("Sigma 18-50 Fuji X", searcher=searcher))
    assert [row["title"] for row in result["items"]] == ["Sigma 18-50mm f2.8 Fuji X"]


def test_unknown_provider_does_not_scrape():
    called = []

    async def searcher(provider, query):
        called.append(provider)
        return []

    result = asyncio.run(search_listings("Fujifilm X-T5", providers=["subito"], searcher=searcher))
    assert result["items"] == []
    assert called == []
    assert clamp_providers(["OLX", "olx", "ebay_it"]) == ["olx"]


def test_execute_tool_parses_model_json_and_converts_currency():
    async def searcher(provider, query):
        return [_item("Fujifilm X-H2", price=5000, platform="olx", currency="RON")]

    result = asyncio.run(
        execute_tool(
            "search_listings",
            '{"query": "Fujifilm X-H2", "providers": ["olx"], "limit": 5}',
            searcher=searcher,
        )
    )
    assert result["items"][0]["price_eur"] == 1000.0
    assert result["items"][0]["platform"] == "olx"

    unknown = asyncio.run(execute_tool("web_search", {"query": "Fujifilm X-T5"}))
    assert unknown == {"error": "tool sconosciuto"}
