"""
Veron case-seuranta: paaohjelma.

Ajo:
    python main.py            normaali paivittainen ajo
    python main.py --seed     ensimmainen ajo, lukee seed_since-arvot
                              sources.yaml:sta ja merkitsee niita vanhemmat
                              ratkaisut jo raportoiduiksi
    python main.py --dry-run  hakee ja tulostaa, ei kirjoita state.json:ia

Tila sailytetaan state.json:issa. Tunniste on ratkaisun URL ilman
kyselyparametreja ja paattavaa kauttaviivaa, ei paivays: hallinto-oikeuksien
ratkaisut ilmestyvat sivuille viiveella ja lista on jarjestetty
julkaisupaivan mukaan, joten paivaykseen ei voi luottaa. Kun tunniste on
URL, myohaan ilmestyva toukokuinen ratkaisu paatyy silti seurantaan.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import sys
from zoneinfo import ZoneInfo

import yaml

from fetchers import Item, fetch_source, fmt
from filtering import TaxFilter, apply_filter
from render import render_all

ROOT = pathlib.Path(__file__).parent
STATE_PATH = ROOT / "state.json"
CONFIG_PATH = ROOT / "sources.yaml"
DOCS = ROOT / "docs"


def load_state() -> dict:
    if STATE_PATH.exists():
        try:
            return json.loads(STATE_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            print("state.json on rikki, aloitetaan tyhjasta", file=sys.stderr)
    return {"last_run": None, "items": {}}


def item_to_record(item: Item, first_seen: str, last_seen: str) -> dict:
    return {
        "title": item.title,
        "url": item.url,
        "source_id": item.source_id,
        "source_name": item.source_name,
        "category": item.category,
        "kind": item.kind,
        "date": item.date.isoformat() if item.date else None,
        "date_label": item.date_label,
        "keywords": item.keywords,
        "dnro": item.dnro,
        "confidence": item.confidence,
        "matched": item.matched,
        "first_seen": first_seen,
        "last_seen": last_seen,
        "revised": False,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", action="store_true", help="ensimmainen ajo, kayta seed_since-arvoja")
    ap.add_argument("--dry-run", action="store_true", help="ala kirjoita tiedostoja")
    args = ap.parse_args()

    cfg = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
    tz = ZoneInfo(cfg["site"].get("timezone", "Europe/Helsinki"))
    now = dt.datetime.now(tz)
    today = now.date()

    state = load_state()
    items_state: dict = state.setdefault("items", {})
    known = set(items_state)

    tax_filter = TaxFilter(cfg.get("filter", {}))

    results = []
    new_keys: list[str] = []

    for source in cfg["sources"]:
        result = fetch_source(source, known)
        if result.ok:
            result.items = apply_filter(result.items, tax_filter, source.get("tax_filter", False))
        results.append(result)

        status = f"{len(result.items):>3} kpl" if result.ok else f"VIRHE {result.error[:70]}"
        print(f"  {source['id']:<16} {status}")

        if not result.ok:
            continue

        seed_since = None
        if args.seed and source.get("seed_since"):
            seed_since = dt.date.fromisoformat(str(source["seed_since"]))

        for item in result.items:
            key = item.key
            if key in items_state:
                # Paivita mahdollisesti tarkentuneet tiedot, sailyta first_seen.
                record = items_state[key]
                first_seen = record.get("first_seen", today.isoformat())
                merged = item_to_record(item, first_seen, today.isoformat())
                if not merged["date"] and record.get("date"):
                    merged["date"] = record["date"]
                    merged["date_label"] = record.get("date_label", "")
                if not merged["keywords"] and record.get("keywords"):
                    merged["keywords"] = record["keywords"]

                # Vanha ohje voidaan paivittaa, jolloin se nousee takaisin
                # vero.fi:n "Uusimmat"-lohkoon. URL pysyy samana, joten ainoa
                # merkki on paivaysselitteen muutos. Kasin tehdyssa
                # seurannassa tallainen ohje raportoidaan, joten se
                # nostetaan tassakin uudelleen uusien listalle.
                old_label = record.get("date_label", "")
                if (source.get("report_updates")
                        and old_label and merged["date_label"]
                        and merged["date_label"] != old_label):
                    merged["first_seen"] = today.isoformat()
                    merged["revised"] = True
                    items_state[key] = merged
                    new_keys.append(key)
                    continue

                merged["revised"] = record.get("revised", False)
                items_state[key] = merged
                continue

            if seed_since is not None and item.date and item.date < seed_since:
                # Vanha, jo manuaalisesti raportoitu: merkitaan nahdyksi
                # ilman etta se paatyy uusien listalle. first_seen on
                # ratkaisun oma paivays, mutta viimeistaan eilen: tanaan
                # annettu ratkaisu on jo kasin raportoitu, eika sen pida
                # nakya ensimmaisessa automaattisessa viestissa.
                seen_day = min(item.date, today - dt.timedelta(days=1))
                items_state[key] = item_to_record(
                    item, seen_day.isoformat(), today.isoformat()
                )
                continue

            items_state[key] = item_to_record(item, today.isoformat(), today.isoformat())
            new_keys.append(key)

    state["last_run"] = now.isoformat(timespec="seconds")
    state["last_run_date"] = today.isoformat()

    # Karsi tilasta ne, jotka ovat pudonneet lahteiden listoilta yli
    # archive_days vuorokautta sitten. Karsinta tehdaan last_seen-paivan
    # eika antopaivan mukaan: jos ratkaisu nakyy yha lahteen listalla, se
    # pidetaan tilassa, jotta se ei ilmesty huomenna uutena.
    cutoff = today - dt.timedelta(days=int(cfg["site"].get("archive_days", 120)))
    for key in [k for k, v in items_state.items()
                if dt.date.fromisoformat(
                    v.get("last_seen") or v.get("first_seen") or today.isoformat()
                ) < cutoff]:
        del items_state[key]

    print(f"\nUusia: {len(new_keys)} | seurannassa yhteensa: {len(items_state)}")
    for key in new_keys:
        rec = items_state[key]
        print(f"  + [{rec['category']}] {rec['title'][:80]}")

    if args.dry_run:
        print("\n--dry-run: tiedostoja ei kirjoitettu")
        return 0

    DOCS.mkdir(exist_ok=True)
    render_all(cfg, state, results, now, DOCS)
    STATE_PATH.write_text(
        json.dumps(state, ensure_ascii=False, indent=1, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"\nKirjoitettu {DOCS/'index.html'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
