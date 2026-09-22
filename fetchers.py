"""
Veron case-seuranta: lahteiden haku.

Nelja lahdetyyppia kattaa kaikki seurattavat lahteet:

  vero_api      vero.fi:n listasivut ovat Vue-komponentteja, mutta ne
                hakevat sisaltonsa omalta rajapinnaltaan
                /api/search/results. Sita kutsutaan tassa suoraan.
                Etusivun "Uusimmat ..." -lohkoihin ei voi luottaa: ne
                ovat karsittu poiminta eivatka sisalla kaikkea, esim.
                9.9.2026 annettu "CRS - lista osallistuvista
                lainkayttoalueista" puuttui niista kokonaan.

                Parametrit ovat rootFilter (yksikko, ei monikkoa) ja
                typeId, ja sort=1 tarkoittaa uusin ensin. Sivun oma
                oletus sort=3 on aakkosjarjestys, joka nostaisi
                karkeen vuosien takaisia ohjeita.

                Rajapinnan Date on muokkauspaiva, ei antopaiva, joten
                antopaiva, avainsanat ja diaarinumero luetaan edelleen
                yksityiskohtasivulta. Se haetaan vain kun kohde on uusi
                tai kun rajapinnan Date on muuttunut, jolloin ajo
                pysyy nopeana.

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

  finlex_hao    finlex.fi on Next.js-sovellus, jonka lista ei ole
                HTML:ssa vaan RSC-kuormassa self.__next_f.push([1,"..."])
                -merkkijonoina. BeautifulSoup ei loyda sielta yhtaan
                linkkia, joten lista luetaan saannollisilla lausekkeilla
                raakatekstista. Vuosisivu palauttaa koko vuoden kerralla,
                joten sivutusta ei tarvita.

                Finlex ja tuomioistuimet.fi julkaisevat osin eri
                ratkaisuja, ja molemmat ovat mukana tahallaan. Sama
                ratkaisu eri osoitteessa tuottaa kaksoiskappaleen, mutta
                se on pienempi haitta kuin valiin jaava ratkaisu.
"""

from __future__ import annotations

import datetime as dt
import html
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
    api_date: str = ""              # vero.fi-rajapinnan muokkauspaiva sellaisenaan

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


def get_json(url: str, params: dict) -> dict:
    """Hae JSON-rajapinnasta. Sama uudelleenyritys kuin get()."""
    last = None
    for attempt in range(RETRIES):
        try:
            r = _session.get(url, params=params, timeout=TIMEOUT,
                             headers={"Accept": "application/json"})
            r.raise_for_status()
            return r.json()
        except Exception as exc:  # noqa: BLE001
            last = exc
            if attempt < RETRIES - 1:
                time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"{url}: {last}")


def clean(text: str) -> str:
    """Poista pehmeat tavuviivat ja tuplavalit."""
    return re.sub(r"\s+", " ", (text or "").translate(SOFT)).strip()


COURT_BEFORE_DATE = re.compile(r"\s*\d{1,2}\.\d{1,2}\.\d{4}")
DECISION_NO = re.compile(r"(\d+)\s*/\s*(\d{4})")


def fingerprints(item: "Item", group: str) -> tuple[str, str, bool]:
    """Tunnisteet, joilla sama ratkaisu tunnistetaan kahdesta eri lahteesta.

    Hallinto-oikeuksien ratkaisut tulevat seka tuomioistuimet.fi:sta etta
    Finlexista, ja osoite on eri, joten URL ei riita tunnisteeksi.

    Palautetaan kolme arvoa:

      tarkka      tuomioistuin + antopaiva + otsikon numerot. Tama on
                  oikea tunniste silloin kun molemmat lahteet kayttavat
                  ratkaisunumeroa, ja se erottaa myos saman paivan
                  ratkaisut toisistaan: Helsingin HAO antoi 13.5.2026
                  kaksi eri veroratkaisua, 3313/2026 ja 3315/2026, joilla
                  on taysin samat asiasanat.

      valjä       tuomioistuin + antopaiva ilman numeroa.

      epaselva    tosi, jos otsikon numeron vuosi ei ole antovuosi. Silloin
                  otsikossa on diaarinumero eika ratkaisunumeroa, esim.
                  "Vaasan HaO 6.3.2026 586/2025", jolloin numeroa ei voi
                  verrata toisen lahteen numeroon lainkaan. Vain nailla
                  ratkaisuilla valjaa tunnistetta saa kayttaa.
    """
    if not group or not item.date:
        return "", "", False
    court = re.sub(r"\W", "", COURT_BEFORE_DATE.split(item.title, 1)[0].lower())
    if not court:
        return "", "", False

    loose = f"{group}|{court}|{item.date.isoformat()}"
    nums = DECISION_NO.findall(item.title)
    if not nums:
        return "", loose, True

    strict = loose + "|" + ",".join(sorted(n for n, _ in nums))
    ambiguous = not any(int(y) == item.date.year for _, y in nums)
    return strict, loose, ambiguous


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

VERO_API = "https://www.vero.fi/api/search/results"
VERO_BASE = "https://www.vero.fi"


def fetch_vero_api(source: dict, known: dict) -> list[Item]:
    """Lue yksi vero.fi:n listaus (ohjeet, paatokset, kannanotot, KVL) rajapinnasta.

    rootFilter ja typeId kertovat kumpi listaus on kyseessa, sort=1 on
    uusin ensin. page_size kertoo montako uusinta luetaan; oletus riittaa
    hyvin pitkallekin poissaololle, koska listaus on paivamaarajarjestyksessa.
    """
    data = get_json(VERO_API, {
        "query": "",
        "language": "fi",
        "page": 1,
        "pageSize": int(source.get("page_size", 30)),
        "rootFilter": int(source["root_filter"]),
        "typeId": int(source["type_id"]),
        "sort": 1,
        "showAllVersions": "false",
    })

    hits = data.get("Hits")
    if not hits:
        raise RuntimeError(f'rajapinta ei palauttanut osumia (TotalCount={data.get("TotalCount")})')

    items: list[Item] = []
    seen: set[str] = set()

    for hit in hits:
        friendly = (hit.get("FriendlyUrl") or "").strip()
        title = clean(hit.get("Title") or "")
        if not friendly or not title:
            continue
        url = requests.compat.urljoin(VERO_BASE, friendly)
        key = url.split("?")[0].rstrip("/")
        if key in seen:
            continue
        seen.add(key)

        api_date = clean(hit.get("Date") or "")

        # Yksityiskohtasivulta saadaan antopaiva, avainsanat ja diaarinumero,
        # joita rajapinta ei anna. Se haetaan vain kun kohde on uusi tai kun
        # rajapinnan paivays on muuttunut. Paivitetty ohje nakyy juuri Date-
        # kentan muutoksena, joten tama ei hukkaa paivitystietoa.
        record = known.get(key) if isinstance(known, dict) else None
        need_detail = record is None or record.get("api_date") != api_date

        date, date_label, keywords, dnro = None, "", "", ""
        if need_detail:
            try:
                date, date_label, keywords, dnro, better_title = fetch_vero_detail(url)
                if better_title:
                    title = better_title
            except Exception:  # noqa: BLE001
                pass
        elif record:
            date = dt.date.fromisoformat(record["date"]) if record.get("date") else None
            date_label = record.get("date_label", "")
            keywords = record.get("keywords", "")
            dnro = record.get("dnro", "")
            title = record.get("title") or title

        if date is None:
            date = parse_fi_date(api_date)
            if date and not date_label:
                date_label = f"päivitetty {fmt(date)}"

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
                api_date=api_date,
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
    silloin paivityspaiva, koska sen mukaan ohje asettuu seurannassa
    oikealle kohdalle: kasin tehdyssa seurannassa 24.2.2021 annettu
    "CRS - lista osallistuvista lainkayttoalueista" raportoidaan sina
    paivana kun se paivitetaan, 9.9.2026, ei vuonna 2021. Selite kertoo
    molemmat paivat, jotta nakee miksi vanha ohje on listalla.
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
        return (max(given, updated),
                f"antopäivä {fmt(given)}, päivitetty {fmt(updated)}",
                keywords, dnro, title)
    chosen = given or updated
    return chosen, (f"antopäivä {fmt(chosen)}" if chosen else ""), keywords, dnro, title


def fmt(d: dt.date | None) -> str:
    return f"{d.day}.{d.month}.{d.year}" if d else ""


# ---------------------------------------------------------------------------
# KHO RSS
# ---------------------------------------------------------------------------

SWEDISH = re.compile(r"^(HFD|HD|MD|AD)[:\s]", re.I)


def fetch_kho_rss(source: dict, known: dict) -> list[Item]:
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


def fetch_court_cards(source: dict, known: dict) -> list[Item]:
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


# ---------------------------------------------------------------------------
# Finlex: hallinto-oikeuksien ratkaisut
# ---------------------------------------------------------------------------

FINLEX_BASE = "https://www.finlex.fi"
FINLEX_HREF = re.compile(r'"href":"(/fi/oikeuskaytanto/[a-z-]+/\d{4}/[^"]+)"')
FINLEX_TITLE = re.compile(r'"span",null,\{"children":"([^"]+)"')
FINLEX_CHIP = re.compile(r'"div","([^"]+)",\{"className":"[^"]*chip')


def fetch_finlex_hao(source: dict, known: dict) -> list[Item]:
    """Lue Finlexin vuosisivu hallinto-oikeuksien ratkaisuista.

    Sisalto on Next.js:n RSC-kuormassa JavaScript-merkkijonoina, joissa
    lainausmerkit on kenoviivatettu. Kuorma puretaan kertaalleen, minka
    jalkeen jokainen ratkaisu on href, sita seuraava otsikko ja
    keywordChips-lohkon asiasanat. Otsikko sisaltaa myos antopaivan.

    Osoitteessa on vuosi, ja years_back kertoo montako edellista vuotta
    luetaan lisaksi. Yksi riittaa: tammikuussa edellisen vuoden
    ratkaisuja ilmestyy viela listalle.
    """
    items: list[Item] = []
    seen: set[str] = set()
    this_year = dt.date.today().year
    years = [this_year - n for n in range(int(source.get("years_back", 0)) + 1)]

    for year in years:
        url_year = source["url"].format(year=year)
        raw = get(url_year)
        text = html.unescape(raw).replace('\\"', '"').replace("\\n", "\n")

        matches = list(FINLEX_HREF.finditer(text))
        if not matches and year == this_year:
            raise RuntimeError("Finlexin listasta ei loytynyt yhtaan ratkaisulinkkia")

        bounds = [m.start() for m in matches] + [len(text)]
        items.extend(_finlex_items(source, text, matches, bounds, seen))

    return items


def _finlex_items(source: dict, text: str, matches: list, bounds: list, seen: set) -> list[Item]:
    items: list[Item] = []
    for i, m in enumerate(matches):
        url = requests.compat.urljoin(FINLEX_BASE, m.group(1))
        key = url.rstrip("/")
        if key in seen:
            continue
        seen.add(key)

        segment = text[m.start():bounds[i + 1]]

        title_m = FINLEX_TITLE.search(segment)
        if not title_m:
            continue
        title = clean(title_m.group(1))
        if not title:
            continue

        # Asiasanat ovat chip-elementteina vasta keywordChips-lohkon jalkeen.
        chips_at = segment.find("keywordChips")
        keywords = ""
        if chips_at >= 0:
            chips = [clean(c) for c in FINLEX_CHIP.findall(segment[chips_at:])]
            keywords = " – ".join(dict.fromkeys(c for c in chips if c))

        # Antopaiva on otsikossa: "Helsingin HAO 13.5.2026 3315/2026".
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
    "vero_api": fetch_vero_api,
    "kho_rss": fetch_kho_rss,
    "court_cards": fetch_court_cards,
    "finlex_hao": fetch_finlex_hao,
}


def fetch_source(source: dict, known: dict) -> SourceResult:
    fn = FETCHERS.get(source["type"])
    if fn is None:
        return SourceResult(source["id"], source["name"], False, [], f'tuntematon tyyppi {source["type"]}')
    try:
        return SourceResult(source["id"], source["name"], True, fn(source, known))
    except Exception as exc:  # noqa: BLE001
        return SourceResult(source["id"], source["name"], False, [], str(exc))
