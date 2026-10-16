"""Grok chat wired to the existing Vinted and OLX scrapers.

The model only sees one tool, ``search_listings``. The tool refuses every
other marketplace and every query that is not Fujifilm mirrorless gear or a
Fuji-mount lens (Fujinon or third-party). Scraping still goes through
:class:`~arbitrage_sniper.providers.base.BaseProvider`.

    python main.py --grok
    python main.py --grok "Fujifilm X-T5 su Vinted"
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import re
from typing import Any, Awaitable, Callable

from .browser import BrowserManager
from .config import settings
from .currency import to_eur
from .matching import is_relevant, normalize
from .models import Item
from .providers.olx import OlxProvider
from .providers.vinted import VintedProvider

logger = logging.getLogger("arbitrage_sniper.grok_bot")

ALLOWED_PROVIDERS = ("vinted", "olx")
MAX_ITEMS = 15
MAX_TOOL_ROUNDS = 6

# (provider name, query) -> listings. Tests inject a fake.
Searcher = Callable[[str, str], Awaitable[list[Item]]]

_PROVIDER_TYPES = {
    "vinted": VintedProvider,
    "olx": OlxProvider,
}

SYSTEM_PROMPT = """\
Sei un cercatore di annunci usati. Rispondi in italiano, in modo breve.

Puoi cercare solo su due siti, tramite il tool search_listings:
- vinted
- olx

Non usare altri provider. Non usare la ricerca web. Non inventare annunci, prezzi o link. Se il tool restituisce una lista vuota o un errore, dillo e fermati.

Cosa cercare
Solo queste due categorie:
1. Corpi macchina Fujifilm mirrorless: serie X (X-T, X-H, X-Pro, X-E, X-S, X-A, X100) e serie GFX.
2. Obiettivi per attacco Fujifilm X o GFX. Marchi ammessi: Fujinon (XF, XC, GF) e terze parti, tra cui Sigma, Tamron, Viltrox, TTArtisan, 7Artisans, Meike, Samyang, Laowa, Voigtländer, Zeiss, Sirui, Tokina. Un obiettivo di terza parte entra solo se il titolo indica attacco Fuji, X-mount o GFX.

Scarta, anche se il tool li restituisce:
- altri marchi di corpi (Sony, Canon, Nikon, e simili);
- obiettivi per altri attacchi, salvo che il titolo dica esplicitamente Fuji / X-mount / GFX;
- accessori: batteria, caricatore, grip, tracolla, paraluce, tappi, adattatori, scatola solo, flash, filtri;
- pezzi di ricambio e articoli "for parts" / non funzionanti.

Come chiamare il tool
- providers deve essere solo ["vinted"], solo ["olx"], oppure ["vinted", "olx"]. Mai un altro nome.
- Una query = un modello o un obiettivo, non una frase lunga. Esempi validi: "Fujifilm X-T5", "Fuji X-H2", "Fujifilm GFX 50S", "Fujifilm XF 35mm", "Viltrox 27mm Fuji", "Sigma 18-50 Fuji X".
- limit massimo 15.
- Se l'utente non indica il sito, cerca su entrambi.
- Se l'utente chiede un modello preciso, fai una sola query con quel modello.
- Se l'utente chiede in modo generico ("che X-T5 ci sono", "obiettivi Fuji"), fai al massimo 4 query in totale, le più aderenti alla richiesta. Non barrare tutto il catalogo.

Come rispondere
Per ogni annuncio tieni solo ciò che arriva dal tool:
- titolo
- prezzo in euro
- sito (vinted oppure olx)
- link

Ordina dal prezzo più basso. Non stimare se è un affare e non confrontare con altri siti. Se un campo manca nel tool, omettilo.
"""

SEARCH_TOOL = {
    "name": "search_listings",
    "description": (
        "Cerca annunci usati solo su Vinted e OLX. "
        "Una query = un corpo Fujifilm mirrorless o un obiettivo per attacco Fuji X o GFX, "
        "anche di marca terza se l'attacco è Fuji."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "query": {"type": "string"},
            "providers": {
                "type": "array",
                "items": {"type": "string", "enum": ["vinted", "olx"]},
            },
            "limit": {"type": "integer", "minimum": 1, "maximum": MAX_ITEMS},
        },
        "required": ["query"],
    },
}

_BODY_RE = re.compile(
    r"\b("
    r"x\s?t\s?\d{1,2}"
    r"|x\s?h\s?\d\s?s?"
    r"|x\s?pro\s?\d"
    r"|x\s?e\s?\d"
    r"|x\s?s\s?\d{2}"
    r"|x\s?a\s?\d"
    r"|x\s?m\s?1"
    r"|x\s?100(?:\s?[a-z]{1,2})?"
    r"|gfx(?:\s?\d{2,3}\s?[a-z]{0,2})?"
    r")\b"
)
_BRAND_RE = re.compile(
    r"\b("
    r"viltrox|sigma|tamron|meike|samyang|rokinon|laowa|voigtlander|"
    r"zeiss|sirui|tokina|irix|astrhori|pergear|kamlan|"
    r"tt\s?artisan|7\s?artisans"
    r")\b"
)
_FUJI_BRAND_RE = re.compile(r"\b(fujifilm|fujinon|fuji)\b")
_LENS_MARK_RE = re.compile(r"\b(xf|xc|gf)\b")
_STRICT_MOUNT_RE = re.compile(r"\b(xf|xc|gf|fujinon)\b|\bx\s+mount\b|\battacco\s+x\b")
_MOUNT_RE = re.compile(r"\b(fujifilm|fujinon|fuji|xf|xc|gf|gfx)\b|\bx\s+mount\b|\battacco\s+x\b")
_OTHER_BRAND_RE = re.compile(
    r"\b(sony|canon|nikon|lumix|panasonic|olympus|leica|pentax|eos|alpha)\b"
)
_MM_PAIR_RE = re.compile(r"\b(\d{1,3})\s+(\d{1,3})\s?mm\b")
_MM_RE = re.compile(r"\b(\d{1,3})\s?mm\b")
_ZOOM_RE = re.compile(r"\b(\d{2})\s+(\d{2,3})\b")
_EXTRA_EXCLUDE = [
    "adapter",
    "adaptor",
    "adattatore",
    "flash",
    "blit",
    "blitz",
    "filter",
    "filtru",
    "filtro",
    "cage",
    "gabbia",
    "custodia",
]

_OUT_OF_SCOPE = (
    "Fuori ambito: solo corpi Fujifilm mirrorless e obiettivi per attacco Fuji X o GFX."
)


def _norm(text: str | None) -> str:
    folded = (text or "").lower()
    for src, dst in (("ä", "a"), ("ö", "o"), ("ü", "u"), ("é", "e"), ("è", "e")):
        folded = folded.replace(src, dst)
    return normalize(folded)


def _canon(token: str) -> str:
    return re.sub(r"\s+", "", token)


def bodies(text: str) -> set[str]:
    """Canonical Fujifilm body keys found in ``text`` (``xt5``, ``xh2s``, ``gfx50s``)."""
    return {_canon(match.group(0)) for match in _BODY_RE.finditer(_norm(text))}


def focals(text: str) -> set[int]:
    """Focal lengths in millimetres mentioned in ``text``."""
    norm = _norm(text)
    found: set[int] = set()
    covered: list[tuple[int, int]] = []
    for match in _MM_PAIR_RE.finditer(norm):
        start, end = int(match.group(1)), int(match.group(2))
        if _focal_ok(start) and _focal_ok(end) and end > start:
            found.add(start)
            found.add(end)
            covered.append(match.span())
    for match in _MM_RE.finditer(norm):
        if any(start <= match.start() < end for start, end in covered):
            continue
        value = int(match.group(1))
        if _focal_ok(value):
            found.add(value)
    for match in _ZOOM_RE.finditer(norm):
        if any(start <= match.start() < end for start, end in covered):
            continue
        start, end = int(match.group(1)), int(match.group(2))
        if _focal_ok(start) and _focal_ok(end) and end > start:
            found.add(start)
            found.add(end)
    return found


def _focal_ok(value: int) -> bool:
    return 8 <= value <= 600


def third_party_brands(text: str) -> set[str]:
    return {_canon(match.group(0)) for match in _BRAND_RE.finditer(_norm(text))}


def _has_fuji_brand(norm: str) -> bool:
    return _FUJI_BRAND_RE.search(norm) is not None


def query_in_scope(query: str) -> bool:
    """True when the search string itself is Fujifilm gear or a Fuji-mount lens."""
    norm = _norm(query)
    if not norm:
        return False
    if _has_fuji_brand(norm):
        return True
    return bool(third_party_brands(norm) and _MOUNT_RE.search(norm))


def is_fuji_listing(title: str) -> bool:
    """True for a Fujifilm mirrorless body or a lens that states a Fuji mount."""
    if not title or not is_relevant(title, [], _EXTRA_EXCLUDE):
        return False
    norm = _norm(title)
    other = _OTHER_BRAND_RE.search(norm) is not None
    strict_mount = _STRICT_MOUNT_RE.search(norm) is not None
    if other and not strict_mount:
        return False
    if _has_fuji_brand(norm) and bodies(title):
        return True
    if _has_fuji_brand(norm) and (strict_mount or _LENS_MARK_RE.search(norm) or focals(title)):
        return True
    return bool(third_party_brands(title) and _MOUNT_RE.search(norm) and focals(title))


def listing_matches_query(title: str, query: str) -> bool:
    """Keep a listing only if it is in scope and agrees with the asked model."""
    if not is_fuji_listing(title):
        return False
    asked_bodies = bodies(query)
    if asked_bodies and not _bodies_compatible(asked_bodies, bodies(title)):
        return False
    asked_focals = focals(query)
    if asked_focals and not asked_focals <= focals(title):
        return False
    asked_brands = third_party_brands(query)
    if asked_brands and not (asked_brands & third_party_brands(title)):
        return False
    return True


def _bodies_compatible(asked: set[str], found: set[str]) -> bool:
    for query_key in asked:
        for title_key in found:
            if title_key == query_key:
                return True
            if query_key == "gfx" and title_key.startswith("gfx"):
                return True
    return False


def clamp_providers(providers: Any) -> list[str]:
    """Keep only ``vinted`` and ``olx``, in the order the model asked."""
    if providers is None:
        return list(ALLOWED_PROVIDERS)
    if isinstance(providers, str):
        providers = [part for part in providers.replace(",", " ").split() if part]
    if not isinstance(providers, (list, tuple)):
        return []
    chosen: list[str] = []
    for raw in providers:
        name = str(raw).strip().lower()
        if name in _PROVIDER_TYPES and name not in chosen:
            chosen.append(name)
    return chosen


def clamp_limit(limit: Any) -> int:
    try:
        value = int(limit)
    except (TypeError, ValueError):
        value = MAX_ITEMS
    return max(1, min(value, MAX_ITEMS))


def _to_eur(item: Item) -> Item:
    if item.currency and item.currency.upper() != "EUR":
        item.price = to_eur(item.price, item.currency)
        item.currency = "EUR"
    return item


def _public(item: Item) -> dict[str, Any]:
    return {
        "title": item.title,
        "price_eur": round(item.price, 2),
        "platform": item.platform,
        "link": item.link,
    }


async def _default_searcher(browser: BrowserManager, provider_name: str, query: str) -> list[Item]:
    provider = _PROVIDER_TYPES[provider_name](browser)
    return await provider.safe_search(query)


async def search_listings(
    query: str,
    providers: Any = None,
    limit: Any = MAX_ITEMS,
    *,
    browser: BrowserManager | None = None,
    searcher: Searcher | None = None,
) -> dict[str, Any]:
    """Run Vinted and/or OLX and return Fujifilm listings only."""
    query = (query or "").strip()
    if not query_in_scope(query):
        logger.info("rejected out-of-scope query: %s", query)
        return {"items": [], "error": _OUT_OF_SCOPE}

    chosen = clamp_providers(providers)
    if not chosen:
        return {"items": [], "error": "Solo vinted e olx."}

    cap = clamp_limit(limit)

    async def _collect(active_browser: BrowserManager | None) -> list[Item]:
        found: list[Item] = []
        seen: set[str] = set()
        for name in chosen:
            if searcher is not None:
                batch = await searcher(name, query)
            else:
                if active_browser is None:
                    raise RuntimeError("BrowserManager required to scrape")
                batch = await _default_searcher(active_browser, name, query)
            for item in batch:
                _to_eur(item)
                if item.unique_key in seen or not listing_matches_query(item.title, query):
                    continue
                seen.add(item.unique_key)
                found.append(item)
        found.sort(key=lambda it: it.price)
        return found[:cap]

    if browser is not None or searcher is not None:
        items = await _collect(browser)
    else:
        async with BrowserManager() as owned:
            items = await _collect(owned)

    payload: dict[str, Any] = {
        "query": query,
        "providers": chosen,
        "items": [_public(item) for item in items],
    }
    if not items:
        payload["note"] = "nessun annuncio nel perimetro Fujifilm"
    return payload


def _load_arguments(arguments: Any) -> dict[str, Any] | None:
    if isinstance(arguments, dict):
        return arguments
    if isinstance(arguments, str):
        try:
            loaded = json.loads(arguments)
        except json.JSONDecodeError:
            return None
        return loaded if isinstance(loaded, dict) else None
    return None


async def execute_tool(
    name: str,
    arguments: Any,
    *,
    browser: BrowserManager | None = None,
    searcher: Searcher | None = None,
) -> dict[str, Any]:
    """Dispatch one model tool call. Unknown tools never touch the network."""
    if name != SEARCH_TOOL["name"]:
        return {"error": "tool sconosciuto"}
    payload = _load_arguments(arguments)
    if payload is None:
        return {"error": "argomenti non validi", "items": []}
    query = str(payload.get("query") or "").strip()
    if not query:
        return {"error": "query mancante", "items": []}
    return await search_listings(
        query,
        providers=payload.get("providers"),
        limit=payload.get("limit", MAX_ITEMS),
        browser=browser,
        searcher=searcher,
    )


async def answer(
    message: str,
    *,
    browser: BrowserManager,
    searcher: Searcher | None = None,
) -> str:
    """One user turn: let Grok call ``search_listings``, then return its reply."""
    try:
        from xai_sdk import Client
        from xai_sdk.chat import system, tool, tool_result, user
    except ImportError:
        return "Manca il pacchetto xai-sdk. Installalo con: pip install -r requirements.txt"

    if not settings.xai_api_key:
        return "XAI_API_KEY non impostata."

    spec = tool(
        name=SEARCH_TOOL["name"],
        description=SEARCH_TOOL["description"],
        parameters=SEARCH_TOOL["parameters"],
    )
    client = Client(api_key=settings.xai_api_key)
    chat = client.chat.create(
        model=settings.xai_model,
        tools=[spec],
        parallel_tool_calls=False,
    )
    chat.append(system(SYSTEM_PROMPT))
    chat.append(user(message))

    for _ in range(MAX_TOOL_ROUNDS):
        response = chat.sample()
        if not response.tool_calls:
            return (response.content or "").strip() or "Nessuna risposta dal modello."
        chat.append(response)
        for call in response.tool_calls:
            logger.info("tool %s %s", call.function.name, call.function.arguments)
            result = await execute_tool(
                call.function.name,
                call.function.arguments,
                browser=browser,
                searcher=searcher,
            )
            chat.append(
                tool_result(
                    json.dumps(result, ensure_ascii=False),
                    tool_call_id=call.id,
                )
            )
    return "Troppe ricerche in una sola domanda. Chiedi un modello o un obiettivo preciso."


def _startup_error() -> str | None:
    try:
        import xai_sdk  # noqa: F401
    except ImportError:
        return "Manca il pacchetto xai-sdk. Installalo con: pip install -r requirements.txt"
    if not settings.xai_api_key:
        return "XAI_API_KEY non impostata. Aggiungila al .env (vedi .env.example)."
    return None


async def run(message: str | None) -> int:
    """Interactive prompt, or a single message when ``message`` is set."""
    problem = _startup_error()
    if problem:
        logger.error("%s", problem)
        print(problem)
        return 1

    async with BrowserManager() as browser:
        if message:
            print(await answer(message, browser=browser))
            return 0
        print("Grok bot Fuji — solo Vinted e OLX. Riga vuota per uscire.")
        while True:
            try:
                line = input("Cerca: ").strip()
            except EOFError:
                return 0
            if not line or line.lower() in {"exit", "quit", "/exit"}:
                return 0
            print(await answer(line, browser=browser))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Grok bot: Vinted + OLX, Fujifilm mirrorless bodies and Fuji-mount lenses",
    )
    parser.add_argument("message", nargs="*", help="one-shot question; omit for interactive")
    args = parser.parse_args(argv)
    text = " ".join(args.message).strip()
    try:
        return asyncio.run(run(text or None))
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
