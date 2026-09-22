"""
Veron case-seuranta: lahteiden haku.

Kolme lahdetyyppia riittaa kattamaan kaikki nelja seurattavaa lahdetta:

  vero_landing  vero.fi/syventavat-vero-ohjeet/ palvelinrenderoi lohkot
                "Uusimmat ohjeet", "Uusimmat paatokset", "Uusimmat
                kannanotot" ja "Uusimmat ennakkoratkaisut". Listasivut
                (ohje-hakusivu, paatokset, kannanotot, ennakkoratkaisut)
                ovat Vue-komponentteja eivatka palauta linkkeja ilman
                JavaScriptia, joten etusivun lohkot ovat ainoa lahde
                jonka requests + BeautifulSoup nakee.

  kho_rss       kho.fi pyorii WordPressilla ja tarjoaa syotteen
                /feed/rss-feed?post_type=ratkaisut. Huomaa monikko:
                yksikko "ratkaisu" palauttaa HTML-virhesivun. Sama
                ratkaisu tulee syotteeseen kahdesti, suomeksi ja
                ruotsiksi (HFD: ja /sv/), ruotsinkieliset pudotetaan.
                Asiasanat tulevat <category>-elementteina.

  court_cards   tuomioistuimet.fi ja kho.fi kayttavat samaa korttilistaa,
                jossa jokainen ratkaisu on div.content-lift. Otsikko on
                .content-lift__title, asiasanat .content-lift__excerpt ja
                paivays time[datetime] muodossa pp.kk.vvvv. Otsikoissa on
                pehmeita tavuviivoja (\\xad) ja nollan levyisia valeja
                (\\u200b) rivitysta varten, ne pitaa siivota.
"""

from __future__ import annotations

import datetime as dt
import re
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field

import requests
from bs4 import BeautifulSoup

USER_AGENT = (
    "Mozilla/5.0 (compatible; VeroSeuranta/1.0; "
    "+https://github.com/lslander/Veroseuranta)"
)
TIMEOUT = 45
RETRIES = 3

DATE_FI = re.compile(r"(\d{1,2})\.(\d{1,2})\.(\d{4})")
SOFT = dict.fromkeys(map(ord, "\u00ad\u200b\u200c\u200d\ufeff"), None)


@dataclass
class Item:
    source_id: str
    source_name: str
    category: str
    kind: str
    title: str
    url: str
    date: dt.date | None
    date_label: str
    keywords: str = ""              # asiasanat, menevat sahkopostiin
    dnro: str = ""                  # diaarinumero, nakyy vain sivulla
    confidence: str = "varma"       # varma | tarkista
    matched: list[str] = field(default_factory=list)

    @property
    def key(self) -> str:
        return self.url.split("?")[0].rstrip("/")


@dataclass
class SourceResult:
    source_id: str
    name: str
    ok: bool
    items: list[Item]
    error: str = ""


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------

_session = requests.Session()
_session.headers.update({"User-Agent": USER_AGENT, "Accept-Language": "fi,en;q=0.7"})
_page_cache: dict[str, str] = {}


def get(url: str, use_cache: bool = False) -> str:
    """Hae sivu. use_cache sailoo vero.fi:n etusivun neljalle lahteelle."""
    if use_cache and url in _page_cache:
        return _page_cache[url]

    last = None
    for attempt in range(RETRIES):
        try:
            r = _session.get(url, timeout=TIMEOUT)
            r.raise_for_status()
            r.encoding = r.encoding or "utf-8"
            if use_cache:
                _page_cache[url] = r.text
            return r.text
        except Exception as exc:  # noqa: BLE001
            last = exc
            if attempt < RETRIES - 1:
                time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"{url}: {last}")


def clean(text: str) -> str:
    """Poista pehmeat tavuviivat ja tuplavalit."""
    return re.sub(r"\s+", " ", (text or "").translate(SOFT)).strip()


def parse_fi_date(text: str) -> dt.date | None:
    m = DATE_FI.search(text or "")
    if not m:
        return None
    d, mo, y = (int(x) for x in m.groups())
    try:
        return dt.date(y, mo, d)
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# vero.fi
# ---------------------------------------------------------------------------

VERO_ITEM_HREF = re.compile(
    r"/syventavat-vero-ohjeet/(?:ohje-hakusivu|paatokset|kannanotot|ennakkoratkaisut)/\d+/"
)


def fetch_vero_landing(source: dict, known: set[str]) -> list[Item]:
    """Lue yksi "Uusimmat ..." -lohko vero.fi:n syventavien vero-ohjeiden etusivulta."""
    soup = BeautifulSoup(get(source["url"], use_cache=True), "html.parser")

    heading = None
    for tag in soup.find_all(["h2", "h3"]):
        if clean(tag.get_text(" ")).lower() == source["block"].lower():
            heading = tag
            break
    if heading is None:
        raise RuntimeError(f'lohkoa "{source["block"]}" ei loytynyt vero.fi:n etusivulta')

    container = heading.find_parent(["section", "div"])
    items: list[Item] = []
    seen: set[str] = set()

    for a in container.find_all("a", href=True):
        href = a["href"]
        if not VERO_ITEM_HREF.search(href):
            continue
        url = requests.compat.urljoin(source["url"], href)
        if url in seen:
            continue
        seen.add(url)

        title = clean(a.get_text(" "))
        if not title:
            continue

        # Yksityiskohtasivu haetaan aina, myos jo tunnetuille. Syy: vanha ohje
        # voidaan paivittaa ja se nousee silloin takaisin "Uusimmat"-lohkoon.
        # Paivayksen muutos on ainoa tapa havaita se, ja lohkoissa on
        # yhteensa vain parikymmenta kohdetta, joten pyyntoja tulee vahan.
        date, date_label, keywords, dnro = None, "", "", ""
        try:
            date, date_label, keywords, dnro, better_title = fetch_vero_detail(url)
            if better_title:
                title = better_title
        except Exception:  # noqa: BLE001
            pass

        items.append(
            Item(
                source_id=source["id"],
                source_name=source["name"],
                category=source["category"],
                kind=source.get("kind", ""),
                title=title[:240],
                url=url,
                date=date,
                date_label=date_label,
                keywords=keywords[:320],
                dnro=dnro[:80],
            )
        )
    return items


def fetch_vero_detail(url: str) -> tuple[dt.date | None, str, str, str, str]:
    """Poimi yhdelta vero.fi-sivulta antopaiva, paivityspaiva ja avainsanat.

    Sivun ylalaidassa on maaritelmalista, jossa jokainen kentta on
    dt/dd-pari (Antopaiva, Diaarinumero, Avainsanat, joskus Voimassaolo).
    Parit luetaan DOM:ista eika sivun tekstista, koska tekstiin litistettyna
    kentat menevat yhteen putkeen eika niita voi erottaa luotettavasti.

    Ohje voi olla vanha mutta paivitetty tanaan. Palautettava paivays on
    silloin antopaiva, koska se on ratkaisun oma tunniste, mutta selite
    kertoo paivityksesta, jotta on nahtavissa miksi vanha ohje nakyy
    uusimpien listalla.
    """
    soup = BeautifulSoup(get(url), "html.parser")

    fields: dict[str, str] = {}
    info = soup.find(class_="page-version")
    for dt_el in (info or soup).find_all("dt"):
        dd_el = dt_el.find_next_sibling("dd")
        if dd_el is None:
            continue
        label = clean(dt_el.get_text(" ")).rstrip(":").lower()
        if label and label not in fields:
            fields[label] = clean(dd_el.get_text(" "))

    given = parse_fi_date(fields.get("antopäivä", ""))

    # Avainsanat on vain KVL:n ennakkoratkaisuilla. Ohjeissa, paatoksissa ja
    # kannanotoissa on diaarinumero, joka pidetaan erillaan: se kuuluu
    # sivulle mutta ei sahkopostiin, jossa asiasanojen paikka on otsikon
    # perassa suluissa.
    keywords = fields.get("avainsanat", "")
    dnro = fields.get("diaarinumero", "")
    if "tietoa ei saatavilla" in dnro.lower():
        dnro = ""

    text = clean(soup.get_text(" "))
    if given is None:
        m = re.search(r"Antop(?:ä|a)iv(?:ä|a)\s*([\d.]{6,12})", text)
        if m:
            given = parse_fi_date(m.group(1))

    updated = None
    m = re.search(r"Sivu on viimeksi p(?:ä|a)ivitetty\s*([\d.]{6,12})", text)
    if m:
        updated = parse_fi_date(m.group(1))

    title = ""
    h1 = soup.find("h1")
    if h1:
        title = clean(h1.get_text(" "))
        title = re.sub(r"\s*(Syventävä vero-ohje|Verohallinnon päätös)$", "", title).strip()

    if given and updated and updated != given:
        return given, f"antopäivä {fmt(given)}, päivitetty {fmt(updated)}", keywords, dnro, title
    chosen = given or updated
    return chosen, (f"antopäivä {fmt(chosen)}" if chosen else ""), keywords, dnro, title


def fmt(d: dt.date | None) -> str:
    return f"{d.day}.{d.month}.{d.year}" if d else ""


# ---------------------------------------------------------------------------
# KHO RSS
# ---------------------------------------------------------------------------

SWEDISH = re.compile(r"^(HFD|HD|MD|AD)[:\s]", re.I)


def fetch_kho_rss(source: dict, known: set[str]) -> list[Item]:
    root = ET.fromstring(get(source["url"]).encode("utf-8"))
    items: list[Item] = []

    for node in root.findall(".//item"):
        title = clean(node.findtext("title") or "")
        url = (node.findtext("link") or "").strip()
        if not title or not url:
            continue
        if SWEDISH.match(title) or "/sv/" in url:
            continue

        keywords = " – ".join(
            clean(c.text) for c in node.findall("category") if c.text
        )

        date = None
        pub = node.findtext("pubDate") or ""
        m = re.search(r"(\d{1,2})\s+([A-Za-z]{3})\s+(\d{4})", pub)
        if m:
            months = {
                "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
                "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
            }
            mo = months.get(m.group(2).lower())
            if mo:
                try:
                    date = dt.date(int(m.group(3)), mo, int(m.group(1)))
                except ValueError:
                    date = None

        items.append(
            Item(
                source_id=source["id"],
                source_name=source["name"],
                category=source["category"],
                kind=source.get("kind", ""),
                title=title[:240],
                url=url,
                date=date,
                date_label=f"annettu {fmt(date)}" if date else "",
                keywords=keywords[:320],
            )
        )
    return items


# ---------------------------------------------------------------------------
# Korttilistat: tuomioistuimet.fi ja kho.fi
# ---------------------------------------------------------------------------


def fetch_court_cards(source: dict, known: set[str]) -> list[Item]:
    soup = BeautifulSoup(get(source["url"]), "html.parser")
    cards = soup.select("div.content-lift")
    if not cards:
        raise RuntimeError("korttilistaa div.content-lift ei loytynyt")

    items: list[Item] = []
    seen: set[str] = set()

    for card in cards:
        a = card.find("a", href=True)
        title_el = card.find(class_="content-lift__title")
        if a is None or title_el is None:
            continue
        url = requests.compat.urljoin(source["url"], a["href"].strip())
        if url in seen:
            continue
        seen.add(url)

        title = clean(title_el.get_text(" "))
        if not title:
            continue

        excerpt_el = card.find(class_="content-lift__excerpt")
        keywords = clean(excerpt_el.get_text(" ")) if excerpt_el else ""

        date = None
        time_el = card.find("time")
        if time_el is not None:
            date = parse_fi_date(time_el.get("datetime") or time_el.get_text(" "))
        if date is None:
            date = parse_fi_date(title)

        items.append(
            Item(
                source_id=source["id"],
                source_name=source["name"],
                category=source["category"],
                kind=source.get("kind", ""),
                title=title[:240],
                url=url,
                date=date,
                date_label=f"annettu {fmt(date)}" if date else "",
                keywords=keywords[:320],
            )
        )
    return items


FETCHERS = {
    "vero_landing": fetch_vero_landing,
    "kho_rss": fetch_kho_rss,
    "court_cards": fetch_court_cards,
}


def fetch_source(source: dict, known: set[str]) -> SourceResult:
    fn = FETCHERS.get(source["type"])
    if fn is None:
        return SourceResult(source["id"], source["name"], False, [], f'tuntematon tyyppi {source["type"]}')
    try:
        return SourceResult(source["id"], source["name"], True, fn(source, known))
    except Exception as exc:  # noqa: BLE001
        return SourceResult(source["id"], source["name"], False, [], str(exc))
