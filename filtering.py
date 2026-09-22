"""
Verosuodatus KHO:n ja hallinto-oikeuksien ratkaisuille.

Verohallinnon ohjeet, paatokset, kannanotot ja KVL:n ennakkoratkaisut
ovat lahtokohtaisesti kaikki vero-aiheisia, joten niita ei suodateta.
KHO ja HaO ratkaisevat kaikkia hallintolainkayton aloja, joten niista
poimitaan vain veroasiat.

Vertailu tehdaan osajonoina eika sanarajoilla, koska suomen yhdyssanat
vaativat sen: "lahdevero", "kiinteistovero" ja "arvonlisavero" loytyvat
vain osajonolla "vero". Sanarajahaku "\\bvero" jattaisi ne kaikki
loytymatta.

Kaksi tasoa:
  varma     osuma strong-listalta, menee viestiin sellaisenaan
  tarkista  osuma vain maybe-listalta, nakyy sivulla keltaisella
            merkilla mutta menee silti viestiin, koska ohje sanoo
            raportoida matalalla kynnyksella
"""

from __future__ import annotations

import unicodedata

from fetchers import Item


def normalise(text: str) -> str:
    """Pienaakkoset ja yhtenaistetyt valimerkit. Aantosmerkit sailytetaan,
    koska esim. "vahennyskelpoisuus" ja "vähennyskelpoisuus" pitaa molemmat
    loytya, ja siksi hakusanat normalisoidaan samalla tavalla."""
    text = unicodedata.normalize("NFC", text or "").lower()
    for ch in "\u2013\u2014\u2212":
        text = text.replace(ch, "-")
    return text


class TaxFilter:
    def __init__(self, cfg: dict):
        self.strong = [normalise(w) for w in cfg.get("strong", [])]
        self.maybe = [normalise(w) for w in cfg.get("maybe", [])]
        self.exclude = [normalise(w) for w in cfg.get("exclude", [])]

    def classify(self, item: Item) -> tuple[bool, str, list[str]]:
        """Palauttaa (raportoidaanko, varmuus, osuneet hakusanat)."""
        haystack = normalise(f"{item.title} {item.keywords}")

        if any(w in haystack for w in self.exclude):
            return False, "", []

        hits_strong = [w for w in self.strong if w in haystack]
        if hits_strong:
            return True, "varma", hits_strong

        hits_maybe = [w for w in self.maybe if w in haystack]
        if hits_maybe:
            return True, "tarkista", hits_maybe

        return False, "", []


def apply_filter(items: list[Item], tax_filter: TaxFilter, enabled: bool) -> list[Item]:
    if not enabled:
        return items
    kept: list[Item] = []
    for item in items:
        report, confidence, matched = tax_filter.classify(item)
        if report:
            item.confidence = confidence
            item.matched = matched
            kept.append(item)
    return kept
