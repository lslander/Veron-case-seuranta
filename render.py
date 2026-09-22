"""
Veron case-seuranta: sivun ja sahkopostimallin muodostus.

Tuottaa kaksi tiedostoa docs-kansioon:
  index.html  seurantasivu, jossa on valmis sahkopostimalli ja
              "Kopioi leikepoydalle" -nappi
  feed.xml    RSS, jos haluat lukea saman virran muualla

Sahkopostimalli rakennetaan selaimessa JavaScriptilla, koska ikkunaa
(1 / 3 / 7 vrk) voi vaihtaa ilman ajoa uudelleen. Kaikki data menee
sivulle JSON-lohkona, josta skripti sen lukee.

Kopiointi tehdaan ClipboardItemilla, joka vie leikepoydalle sseka
text/html etta text/plain. Outlook liittaa silloin linkit klikattavina
eika pitkina osoitteina. Vanhemmille selaimille on varalla
document.execCommand("copy").
"""

from __future__ import annotations

import datetime as dt
import html
import json
import pathlib
import xml.sax.saxutils as sax

# ---------------------------------------------------------------------------
# Verohallinnon varit, poimittu vero.fi:n omasta tyylitiedostosta
# ---------------------------------------------------------------------------
CSS = """
:root{
  --green:#006600;
  --green-dark:#004700;
  --green-mid:#007300;
  --green-bright:#00B140;
  --green-pale:#F0F4F0;
  --border:#CCDFCC;
  --secondary:#80B280;
  --grey:#595959;
  --amber:#B36B00;
  --amber-bg:#FFF6E5;
  --red:#A32020;
}
*{box-sizing:border-box}
body{
  margin:0;
  font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
  font-size:16px;
  line-height:1.55;
  color:#1a1a1a;
  background:#fff;
}
a{color:var(--green-mid)}
a:hover{color:var(--green-dark)}
header{
  background:var(--green);
  color:#fff;
  padding:22px 0 18px;
  border-bottom:5px solid var(--green-bright);
}
header .wrap{max-width:900px;margin:0 auto;padding:0 20px}
header h1{margin:0;font-size:27px;font-weight:700;letter-spacing:-.3px}
header p{margin:5px 0 0;font-size:15px;color:#d6e8d6}
main{max-width:900px;margin:0 auto;padding:26px 20px 60px}
h2{
  font-size:19px;
  margin:34px 0 12px;
  padding-bottom:7px;
  border-bottom:2px solid var(--border);
  color:var(--green-dark);
}
h2:first-child{margin-top:0}
.meta{font-size:13px;color:var(--grey);margin:0 0 20px}
.meta strong{color:#1a1a1a}

/* lahteiden tila */
.sources{display:flex;flex-wrap:wrap;gap:6px;margin:0 0 24px;padding:0;list-style:none}
.sources li{
  font-size:12px;padding:3px 9px;border-radius:11px;
  background:var(--green-pale);border:1px solid var(--border);color:var(--green-dark);
}
.sources li.fail{background:#fdf0f0;border-color:#e8c4c4;color:var(--red)}

/* sahkopostilaatikko */
.mailbox{
  border:1px solid var(--border);
  border-radius:4px;
  background:var(--green-pale);
  padding:16px 18px 18px;
  margin:0 0 30px;
}
.mailbox h2{margin:0 0 12px;border:0;padding:0;font-size:17px}
.mailrow{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin-bottom:12px}
.btn{
  font:inherit;font-size:14px;font-weight:600;
  border:0;border-radius:3px;padding:8px 16px;cursor:pointer;
  background:var(--green);color:#fff;
}
.btn:hover{background:var(--green-dark)}
.btn.sec{background:#fff;color:var(--green-dark);border:1px solid var(--secondary);font-weight:500}
.btn.sec:hover{background:#e8f0e8}
.btn.sec[aria-pressed="true"]{background:var(--green);color:#fff;border-color:var(--green)}
.hint{font-size:12px;color:var(--grey);margin:0 0 10px}
#status{font-size:13px;color:var(--green-dark);font-weight:600;min-height:19px;margin:8px 0 0}
#preview{
  background:#fff;border:1px solid var(--border);border-radius:3px;
  padding:14px 16px;font-size:14.5px;
}
#preview p{margin:0 0 10px}
#preview p:last-child{margin-bottom:0}
.subject{
  font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;
  font-size:13px;background:#fff;border:1px solid var(--border);
  border-radius:3px;padding:7px 10px;margin:0 0 12px;
  display:flex;justify-content:space-between;gap:10px;align-items:center;
}
.subject span{word-break:break-word}
.subject button{
  font:inherit;font-size:12px;border:1px solid var(--secondary);background:#fff;
  color:var(--green-dark);border-radius:3px;padding:3px 9px;cursor:pointer;flex:0 0 auto;
}

/* ratkaisulista */
.group{margin:0 0 6px}
.item{
  border-left:3px solid var(--border);
  padding:9px 0 9px 13px;
  margin:0 0 11px;
}
.item.new{border-left-color:var(--green-bright);background:#f7fcf7}
.item .t{font-weight:600;font-size:15.5px;line-height:1.35}
.item .t a{text-decoration:none}
.item .t a:hover{text-decoration:underline}
.item .d{font-size:13px;color:var(--grey);margin-top:3px}
.item .kw{font-size:13px;color:#333;margin-top:3px}
.tag{
  display:inline-block;font-size:11px;font-weight:700;letter-spacing:.3px;
  padding:1px 7px;border-radius:9px;vertical-align:2px;margin-left:6px;
}
.tag.new{background:var(--green-bright);color:#fff}
.tag.check{background:var(--amber-bg);color:var(--amber);border:1px solid #f0d9a8}
.empty{font-size:14px;color:var(--grey);font-style:italic;margin:0 0 18px}
footer{
  border-top:1px solid var(--border);
  margin-top:40px;padding:16px 20px 40px;
  font-size:12.5px;color:var(--grey);
  max-width:900px;margin-left:auto;margin-right:auto;
}
@media(max-width:600px){
  header h1{font-size:22px}
  main{padding:20px 14px 50px}
}
"""

# ---------------------------------------------------------------------------
# Sahkopostimallin rakentaminen selaimessa
# ---------------------------------------------------------------------------
JS = r"""
const DATA = JSON.parse(document.getElementById("data").textContent);
let windowDays = DATA.defaultWindow;

function fiDate(iso){
  const d = new Date(iso + "T00:00:00");
  return d.getDate() + "." + (d.getMonth() + 1) + ".";
}

/* Ikkunaan kuuluvat ne, jotka on nahty ensimmaisen kerran viimeisten
   n vuorokauden aikana. first_seen, ei antopaiva: HaO julkaisee
   ratkaisuja viiveella ja toukokuinen ratkaisu voi ilmestya syyskuussa. */
function inWindow(rec){
  const seen = new Date(rec.first_seen + "T00:00:00");
  const limit = new Date(DATA.today + "T00:00:00");
  limit.setDate(limit.getDate() - (windowDays - 1));
  return seen >= limit;
}

function groupByCategory(records){
  const out = {};
  for (const cat of DATA.order) out[cat] = [];
  for (const rec of records){
    if (out[rec.category]) out[rec.category].push(rec);
  }
  for (const cat of DATA.order){
    out[cat].sort((a, b) => (b.date || "").localeCompare(a.date || ""));
  }
  return out;
}

/* Suomen kielioppi: "KVL:sta ei" mutta "KVL:sta ja HaO:sta ei". */
function joinFi(parts){
  if (parts.length === 1) return parts[0];
  return parts.slice(0, -1).join(", ") + " ja " + parts[parts.length - 1];
}

/* Ryhmittely lajin mukaan, jotta rivista tulee "Verohallinto antanut
   ohjeen X ja Y" eika kahta erillista rivia. Paivitetyt erotellaan omaksi
   riviksi, koska verbi on eri: "Verohallinto paivittanyt ohjeen X". */
function listSentence(cat, recs, asHtml){
  const label = DATA.categories[cat].email_subject;
  const kinds = {};
  for (const rec of recs){
    const verb = rec.revised ? "päivittänyt" : "antanut";
    const bucket = verb + "\u0000" + rec.kind;
    (kinds[bucket] = kinds[bucket] || []).push(rec);
  }

  const out = [];
  for (const bucket of Object.keys(kinds)){
    const [verb, kind] = bucket.split("\u0000");
    const links = kinds[bucket].map(rec => {
      const kw = rec.keywords ? " (" + rec.keywords + ")" : "";
      if (asHtml){
        return '<a href="' + rec.url + '">' + esc(rec.title) + "</a>" + esc(kw);
      }
      return rec.title + " " + rec.url + kw;
    });
    out.push(label + " " + verb + " " + kind + " " + joinFi(links));
  }
  return out;
}

function esc(s){
  return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

function buildSubject(){
  return DATA.subjectPrefix + " " + fiDate(DATA.today);
}

function buildBody(){
  const recs = DATA.items.filter(inWindow);
  const groups = groupByCategory(recs);

  const empty = DATA.order.filter(c => groups[c].length === 0)
                          .map(c => DATA.categories[c].empty_label);
  const htmlParts = [];
  const textParts = [];

  htmlParts.push("<p>" + esc(DATA.greeting) + "</p>");
  textParts.push(DATA.greeting);

  if (empty.length){
    const tail = windowDays === 1 ? "edellisen viestin jälkeen."
                                  : "viimeisen " + windowDays + " vuorokauden aikana.";
    const s = joinFi(empty) + " ei uusia ratkaisuja " + tail;
    htmlParts.push("<p>" + esc(s) + "</p>");
    textParts.push(s);
  }

  for (const cat of DATA.order){
    if (!groups[cat].length) continue;
    for (const line of listSentence(cat, groups[cat], true)) htmlParts.push("<p>" + line + ".</p>");
    for (const line of listSentence(cat, groups[cat], false)) textParts.push(line + ".");
  }

  htmlParts.push("<p>" + esc(DATA.signature) + "</p>");
  textParts.push(DATA.signature);

  return {html: htmlParts.join("\n"), text: textParts.join("\n\n"), count: recs.length};
}

function render(){
  const body = buildBody();
  document.getElementById("preview").innerHTML = body.html;
  document.getElementById("subject-text").textContent = buildSubject();
  document.getElementById("count").textContent =
    body.count === 0 ? "ei uusia ratkaisuja tässä ikkunassa"
                     : body.count + " ratkaisua tässä ikkunassa";
  for (const b of document.querySelectorAll("[data-window]")){
    b.setAttribute("aria-pressed", String(Number(b.dataset.window) === windowDays));
  }
}

function say(msg){
  const el = document.getElementById("status");
  el.textContent = msg;
  clearTimeout(say._t);
  say._t = setTimeout(() => { el.textContent = ""; }, 3500);
}

/* Outlook sailyttaa linkit vain jos leikepoydalla on text/html. */
async function copyBody(){
  const body = buildBody();
  try {
    await navigator.clipboard.write([new ClipboardItem({
      "text/html": new Blob([body.html], {type: "text/html"}),
      "text/plain": new Blob([body.text], {type: "text/plain"}),
    })]);
    say("Viesti kopioitu. Liitä Outlookiin (Ctrl+V).");
    return;
  } catch (e){ /* vanha selain tai ei lupaa, jatketaan alle */ }

  const sel = window.getSelection();
  const range = document.createRange();
  range.selectNodeContents(document.getElementById("preview"));
  sel.removeAllRanges();
  sel.addRange(range);
  const ok = document.execCommand("copy");
  sel.removeAllRanges();
  say(ok ? "Viesti kopioitu." : "Kopiointi ei onnistunut, valitse teksti käsin.");
}

async function copySubject(){
  try {
    await navigator.clipboard.writeText(buildSubject());
    say("Otsikko kopioitu.");
  } catch (e){
    say("Kopiointi ei onnistunut, valitse teksti käsin.");
  }
}

document.getElementById("copy-body").addEventListener("click", copyBody);
document.getElementById("copy-subject").addEventListener("click", copySubject);
for (const b of document.querySelectorAll("[data-window]")){
  b.addEventListener("click", () => { windowDays = Number(b.dataset.window); render(); });
}
render();
"""


# ---------------------------------------------------------------------------
# Apufunktiot
# ---------------------------------------------------------------------------

MONTHS_FI = [
    "tammikuuta", "helmikuuta", "maaliskuuta", "huhtikuuta", "toukokuuta",
    "kesäkuuta", "heinäkuuta", "elokuuta", "syyskuuta", "lokakuuta",
    "marraskuuta", "joulukuuta",
]


def fi_datetime(now: dt.datetime) -> str:
    return f"{now.day}. {MONTHS_FI[now.month - 1]} {now.year} klo {now:%H:%M}"


def e(text: str) -> str:
    return html.escape(text or "", quote=True)


def sort_key(record: dict) -> tuple:
    """Uusin ensin. Ratkaisut ilman paivaysta loppuun, ei sekaisin."""
    return (record.get("first_seen") or "", record.get("date") or "")


def visible(state: dict, today: dt.date, archive_days: int) -> list[dict]:
    """Sivulla naytetaan vain viimeisten archive_days vuorokauden aikana
    seurantaan tulleet. Tila sisaltaa enemman: se muistaa myos vanhat,
    jotka ovat yha lahteiden listoilla, jotta ne eivat ilmesty uutena,
    seka toisen lahteen kaksoiskappaleet (duplicate_of), jotka pidetaan
    tilassa vain jotta ne eivat ilmesty uutena, mutta joita ei nayteta."""
    cutoff = today - dt.timedelta(days=archive_days)
    kept = [
        r for r in state["items"].values()
        if not r.get("duplicate_of")
        and dt.date.fromisoformat(r.get("first_seen") or today.isoformat()) >= cutoff
    ]
    return sorted(kept, key=sort_key, reverse=True)


# ---------------------------------------------------------------------------
# index.html
# ---------------------------------------------------------------------------

def render_index(cfg: dict, state: dict, results: list, now: dt.datetime) -> str:
    site = cfg["site"]
    email = cfg["email"]
    cats = cfg["categories"]
    order = email["order"]
    today = now.date()

    records = visible(state, today, int(site.get("archive_days", 120)))
    new_today = [r for r in records if r.get("first_seen") == today.isoformat()]

    # Sivulla nakyvat kaikki arkistossa olevat, ryhmiteltyna kategorioittain.
    groups: dict[str, list[dict]] = {c: [] for c in order}
    for rec in records:
        groups.setdefault(rec.get("category", ""), []).append(rec)

    # Lahteiden tila
    source_html = []
    for result in results:
        cls = "" if result.ok else ' class="fail"'
        mark = "✓" if result.ok else "✗"
        title = "" if result.ok else f' title="{e(result.error[:200])}"'
        source_html.append(f"<li{cls}{title}>{mark} {e(result.name)}</li>")

    # Sahkopostidata selaimelle
    data = {
        "today": today.isoformat(),
        "defaultWindow": int(site.get("default_window_days", 1)),
        "subjectPrefix": email["subject_prefix"],
        "greeting": email["greeting"],
        "signature": email["signature"],
        "order": order,
        "categories": {k: dict(v) for k, v in cats.items()},
        "items": [
            {
                "title": r["title"],
                "url": r["url"],
                "category": r.get("category", ""),
                "kind": r.get("kind", "ratkaisun"),
                "keywords": r.get("keywords", ""),
                "date": r.get("date") or "",
                "first_seen": r.get("first_seen") or today.isoformat(),
                "revised": bool(r.get("revised")),
            }
            for r in records
        ],
    }
    data_json = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")

    # Ratkaisulista
    body = []
    for cat in order:
        label = cats[cat]["label"]
        recs = groups.get(cat, [])
        body.append(f"<h2>{e(label)}</h2>")
        if not recs:
            body.append('<p class="empty">Ei ratkaisuja seurantajaksolla.</p>')
            continue
        body.append('<div class="group">')
        for rec in recs:
            is_new = rec.get("first_seen") == today.isoformat()
            tags = ""
            if is_new:
                tags += ('<span class="tag new">PÄIVITETTY</span>' if rec.get("revised")
                         else '<span class="tag new">UUSI</span>')
            if rec.get("confidence") == "tarkista":
                hits = ", ".join(rec.get("matched", []))
                tags += f'<span class="tag check" title="osuma: {e(hits)}">TARKISTA</span>'
            date_label = rec.get("date_label") or ""
            dnro = rec.get("dnro") or ""
            meta = " · ".join(
                x for x in [
                    e(rec.get("source_name", "")),
                    e(date_label),
                    (f"Dnro {e(dnro)}" if dnro else ""),
                ] if x
            )
            kw = rec.get("keywords") or ""
            body.append(
                f'<div class="item{" new" if is_new else ""}">'
                f'<div class="t"><a href="{e(rec["url"])}">{e(rec["title"])}</a>{tags}</div>'
                f'<div class="d">{meta}</div>'
                + (f'<div class="kw">{e(kw)}</div>' if kw else "")
                + "</div>"
            )
        body.append("</div>")

    ok_count = sum(1 for r in results if r.ok)

    return f"""<!DOCTYPE html>
<html lang="fi">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e(site["title"])}</title>
<meta name="description" content="{e(site.get("subtitle", ""))}">
<link rel="alternate" type="application/rss+xml" title="{e(site["title"])}" href="feed.xml">
<style>{CSS}</style>
</head>
<body>
<header>
  <div class="wrap">
    <h1>{e(site["title"])}</h1>
    <p>{e(site.get("subtitle", ""))}</p>
  </div>
</header>

<main>
  <p class="meta">
    Päivitetty <strong>{fi_datetime(now)}</strong> ·
    uusia tänään <strong>{len(new_today)}</strong> ·
    seurannassa {len(records)} ratkaisua ·
    lähteitä {ok_count}/{len(results)} kunnossa
  </p>

  <ul class="sources">
    {"".join(source_html)}
  </ul>

  <section class="mailbox">
    <h2>Sähköpostimalli</h2>
    <p class="hint">
      Jakelu: <strong>{e(email.get("distribution", ""))}</strong>.
      Valitse ikkuna, tarkista teksti ja kopioi. Linkit säilyvät klikattavina Outlookissa.
    </p>

    <div class="subject">
      <span id="subject-text"></span>
      <button id="copy-subject" type="button">Kopioi otsikko</button>
    </div>

    <div class="mailrow">
      <button class="btn sec" type="button" data-window="1">1 vrk</button>
      <button class="btn sec" type="button" data-window="3">3 vrk</button>
      <button class="btn sec" type="button" data-window="7">7 vrk</button>
      <button class="btn" id="copy-body" type="button">Kopioi viesti leikepöydälle</button>
      <span class="hint" style="margin:0" id="count"></span>
    </div>

    <div id="preview"></div>
    <p id="status" role="status" aria-live="polite"></p>
  </section>

  {"".join(body)}
</main>

<footer>
  Sivu rakentuu automaattisesti lähteiden julkisista sivuista ja syötteistä.
  Se on seurannan apuväline, ei virallinen lähde: tarkista ratkaisun sisältö aina
  alkuperäisestä osoitteesta. Ratkaisut poistuvat sivulta
  {int(site.get("archive_days", 120))} vuorokauden jälkeen.
  · <a href="feed.xml">RSS</a>
</footer>

<script type="application/json" id="data">{data_json}</script>
<script>{JS}</script>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# feed.xml
# ---------------------------------------------------------------------------

def render_feed(cfg: dict, state: dict, now: dt.datetime) -> str:
    site = cfg["site"]
    base = site["base_url"].rstrip("/") + "/"
    records = visible(state, now.date(), int(site.get("archive_days", 120)))[:80]

    entries = []
    for rec in records:
        desc_parts = [rec.get("source_name", ""), rec.get("date_label", "")]
        if rec.get("keywords"):
            desc_parts.append(rec["keywords"])
        desc = " · ".join(x for x in desc_parts if x)

        try:
            seen = dt.date.fromisoformat(rec["first_seen"])
            pub = dt.datetime(seen.year, seen.month, seen.day, 9, 0, tzinfo=dt.timezone.utc)
            pub_str = pub.strftime("%a, %d %b %Y %H:%M:%S +0000")
        except Exception:  # noqa: BLE001
            pub_str = now.strftime("%a, %d %b %Y %H:%M:%S %z")

        entries.append(
            "    <item>\n"
            f"      <title>{sax.escape(rec['title'])}</title>\n"
            f"      <link>{sax.escape(rec['url'])}</link>\n"
            f"      <guid isPermaLink=\"true\">{sax.escape(rec['url'])}</guid>\n"
            f"      <description>{sax.escape(desc)}</description>\n"
            f"      <pubDate>{pub_str}</pubDate>\n"
            "    </item>"
        )

    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<rss version="2.0">\n'
        "  <channel>\n"
        f"    <title>{sax.escape(site['title'])}</title>\n"
        f"    <link>{sax.escape(base)}</link>\n"
        f"    <description>{sax.escape(site.get('subtitle', ''))}</description>\n"
        "    <language>fi</language>\n"
        f"    <lastBuildDate>{now.strftime('%a, %d %b %Y %H:%M:%S %z')}</lastBuildDate>\n"
        + "\n".join(entries)
        + "\n  </channel>\n</rss>\n"
    )


# ---------------------------------------------------------------------------

def render_all(cfg: dict, state: dict, results: list, now: dt.datetime,
               docs: pathlib.Path) -> None:
    docs.mkdir(exist_ok=True)
    (docs / "index.html").write_text(render_index(cfg, state, results, now), encoding="utf-8")
    (docs / "feed.xml").write_text(render_feed(cfg, state, now), encoding="utf-8")
    (docs / ".nojekyll").write_text("", encoding="utf-8")
