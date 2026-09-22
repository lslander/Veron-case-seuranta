# Veron case-seuranta

Automatisoi päivittäisen vero-casejen seurannan. Skripti hakee joka arkiaamu
neljä lähdettä, suodattaa vero-aiheiset ratkaisut ja julkaisee ne staattiselle
sivulle, jolla on valmis sähköpostimalli kopioitavaksi HKI TAX -jakelulle.

Sivu on valmis noin klo 8:30, ja viimeinen varmistusajo tehdään klo 9:00,
eli teksti on kopioitavissa ennen klo 9:30 määräaikaa.

## Mitä tämä tekee

Lähteet, jotka haetaan joka ajolla:

| Lähde | Mistä | Suodatus |
|---|---|---|
| Verohallinnon ohjeet, päätökset ja kannanotot | vero.fi "Uusimmat"-lohkot | ei suodateta, kaikki on vero-aiheista |
| KVL:n ennakkoratkaisut | vero.fi | ei suodateta |
| KHO:n vuosikirjaratkaisut ja muut julkaistut päätökset | kho.fi RSS ja korttilista | avainsanasuodatus |
| Hallinto-oikeuksien ratkaisut | tuomioistuimet.fi | avainsanasuodatus |

KHO ja hallinto-oikeudet ratkaisevat kaikkia hallintoasioita, joten niistä
poimitaan vain vero-aiheiset. Suodatin toimii kahdella tasolla. Vahva osuma
(esimerkiksi "vero", "ennakonpidätys", "siirtohinnoittelu", "konserniavustus")
merkitään varmaksi. Heikompi osuma (esimerkiksi "osinko", "yritysjärjestely",
"huojennus") raportoidaan silti, mutta sivulla lukee sen kohdalla "tarkista".
Kynnys on tarkoituksella matala, koska väliin jäänyt ratkaisu on pahempi
virhe kuin ylimääräinen rivi.

Ratkaisun tunniste on sen URL, ei päiväys. Tämä on tärkeää hallinto-oikeuksien
takia: niiden ratkaisut ilmestyvät sivulle viiveellä, joten kesäkuussa annettu
ratkaisu voi ilmestyä listalle vasta syyskuussa. Kun tunniste on URL, myöhässä
ilmestynyt ratkaisu päätyy silti seurantaan.

## Tiedostot

```
veroseuranta/
├── main.py                       päaohjelma
├── fetchers.py                   lähteiden haku ja jäsennys
├── filtering.py                  verosuodatin
├── render.py                     sivun ja sähköpostimallin generointi
├── sources.yaml                  lähteet, suodatinsanat, sähköpostin sanamuodot
├── requirements.txt
├── state.json                    seurannan tila, syntyy ensimmäisellä ajolla
├── docs/                         julkaistava sivu, syntyy ajossa
└── .github/workflows/update.yml  ajastettu ajo
```

Ainoa tiedosto, jota tarvitset muokata arjessa, on `sources.yaml`.

## Vienti GitHubiin

### 1. Luo repo

Mene GitHubiin, paina **New repository**, anna nimeksi esimerkiksi
`veroseuranta`. Valitse **Public** (GitHub Pages vaatii julkisen repon
ilmaisella tilillä). Älä lisää README-tiedostoa, koska se on jo tässä
kansiossa. Paina **Create repository**.

### 2. Lataa tiedostot

Helpoin tapa on raahata tiedostot selaimessa. Avaa uusi repo, paina
**uploading an existing file** ja raahaa kaikki tiedostot ja kansiot tästä
kansiosta kerralla. Varmista, että `.github/workflows/update.yml` tulee
mukana. Selain ei aina näytä pisteellä alkavia kansioita, joten jos se
puuttuu, luo se käsin: paina **Add file → Create new file**, kirjoita
tiedostonimeksi `.github/workflows/update.yml` ja liitä sisältö.

Jos käytät komentoriviä, tämä toimii kansion sisällä:

```bash
git init
git add .
git commit -m "Veron case-seuranta"
git branch -M main
git remote add origin https://github.com/KAYTTAJANIMI/veroseuranta.git
git push -u origin main
```

### 3. Anna Actionsille kirjoitusoikeus

Mene **Settings → Actions → General**, vieritä kohtaan **Workflow
permissions** ja valitse **Read and write permissions**. Paina **Save**.
Ilman tätä ajo ei pysty tallentamaan päivitettyä sivua.

### 4. Kytke GitHub Pages päälle

Mene **Settings → Pages**. Valitse Source-kohtaan **Deploy from a branch**,
branchiksi `main` ja kansioksi `/docs`. Paina **Save**. Osoite on muotoa
`https://KAYTTAJANIMI.github.io/veroseuranta/` ja se on toiminnassa parin
minuutin kuluttua.

Päivitä sama osoite `sources.yaml`-tiedoston kohtaan `site.base_url`.

### 5. Tarkista seed-päivät ennen ensimmäistä ajoa

Tämä on ainoa kohta, jossa voi mennä pieleen jotain, joka ei korjaannu itsestään.

`sources.yaml`-tiedoston jokaisella lähteellä on `seed_since`-päivä. Ensimmäisellä
ajolla sitä vanhemmat ratkaisut merkitään jo raportoiduiksi, eivätkä ne päädy
ensimmäiseen sähköpostiin. Arvon pitää olla **viimeisintä käsin raportoitua
ratkaisua seuraava päivä**.

Nykyiset arvot on asetettu 23.9.2026 tilanteen mukaan, paitsi hallinto-oikeuksilla,
joilla arvo on tarkoituksella vanhempi (14.5.2026), koska HaO:n ratkaisut
ilmestyvät viiveellä ja 13.5.2026 jälkeiset veroratkaisut ovat vielä raportoimatta.

Jos ajat seedin vasta myöhemmin, **nosta päiväykset vastaamaan silloista
tilannetta**. Muuten välissä jo käsin raportoidut ratkaisut tulevat viestiin
toiseen kertaan.

### 6. Aja seed kerran

Mene **Actions**-välilehdelle, valitse vasemmalta **Veron case-seuranta** ja
paina **Run workflow**. Rastita **seed** ja paina vihreää nappia. Ajo kestää
alle minuutin.

Avaa sen jälkeen sivu ja tarkista, että sähköpostimallissa on vain ne
ratkaisut, jotka ovat oikeasti raportoimatta. Jos listalla on jotain jo
raportoitua, nosta `seed_since`-päiviä, poista `state.json` reposta ja aja
seed uudelleen.

Tämän jälkeen seed on tehty, eikä sitä ajeta enää koskaan. Normaalit ajot
tapahtuvat automaattisesti.

## Päivittäinen käyttö

Avaa sivu aamulla. Yläreunassa näkyy, milloin se on päivitetty ja montako
uutta ratkaisua on tullut. Sähköpostimalli-osiossa on kolme ikkunaa:

- **1 vrk** on normaali arkipäivä
- **3 vrk** maanantaiaamuna, jotta viikonloppu tulee mukaan
- **7 vrk** loman jälkeen

Paina **Kopioi otsikko**, liitä se sähköpostin aiheriville, paina sitten
**Kopioi viesti leikepöydälle** ja liitä viestikenttään. Linkit säilyvät
klikattavina Outlookissa, koska kopio tehdään sekä HTML- että
tekstimuodossa. Tarkista teksti silmällä ennen lähetystä.

Jakelu on **HKI TAX**.

## Ajastus

Workflow ajetaan arkisin kolmesti aamussa, noin klo 8:25, 8:40 ja 8:50, ja
vielä kerran klo 9:00. Cron on UTC-ajassa, ja koska Suomi vaihtaa kesäajan ja
talviajan välillä, tiedostossa on molemmat ajat. Käytännössä tämä tarkoittaa,
että kesällä ajoja on neljä ja talvella neljä, ja ylimääräiset ajot eivät
haittaa, koska jo nähty ratkaisu ei päädy uutena listalle toista kertaa.

Kolme ajoa on tahallista. GitHubin ajastetut työt myöhästyvät rutiininomaisesti
5–20 minuuttia, joten yksi ajo klo 9:00 ei riittäisi takaamaan, että sivu on
valmis ennen klo 9:30.

Voit aina ajaa manuaalisesti: **Actions → Veron case-seuranta → Run workflow**
ilman seed-rastia.

## Muokkaaminen

Kaikki arjessa muutettava on `sources.yaml`-tiedostossa. Python-koodia ei
tarvitse koskea.

**Allekirjoitus ja tervehdys:** kohta `email`. Muuta `signature` omaksesi.

**Uusi suodatinsana:** kohta `filter`. Lisää sana `strong`-listalle, jos osuma
on varmasti vero-aiheinen, ja `maybe`-listalle, jos se vaatii silmäilyä.
Vertailu tehdään pienaakkosin ja osajonona ilman sanarajoja, koska suomen
yhdyssanat vaativat sen. Kirjoita siis `ennakonpidät`, älä `ennakonpidätys`,
niin osuma löytyy myös taivutetuista muodoista.

**Väärä positiivinen toistuu:** lisää sana `exclude`-listalle. Se pudottaa
osuman, vaikka vahva sana osuisi.

**Arkiston pituus:** kohta `site.archive_days`, oletuksena 120 vuorokautta.
Tämä säätää, kuinka kauan ratkaisut näkyvät sivulla.

Muutokset tulevat voimaan seuraavassa ajossa. Jos haluat nähdä ne heti, aja
workflow käsin.

## Paikallinen ajo

```bash
pip install -r requirements.txt
python main.py --dry-run     # hakee ja tulostaa, ei kirjoita mitään
python main.py               # normaali ajo
```

`--dry-run` on kätevä suodatinsanojen säätämiseen, koska se näyttää, mitä
uutta tulisi, mutta ei muuta tilaa.

## Jos jokin menee rikki

**Lähde näyttää punaista ruksia sivulla.** Vie hiiri ruksin päälle, niin näet
virheen. Yleensä kyse on hetkellisestä katkosta ja seuraava ajo korjaa sen
itsestään. Jos vika toistuu useana päivänä, lähteen sivurakenne on
todennäköisesti muuttunut ja `fetchers.py` vaatii päivitystä.

**Sivu ei päivity.** Tarkista **Actions**-välilehdeltä, onko ajo mennyt läpi.
Punainen ruksi kertoo virheen. Yleisin syy on unohtunut kirjoitusoikeus
(kohta 3 yllä).

**Sama ratkaisu tulee viestiin kahdesti.** Tämä tarkoittaa, että `state.json`
on nollaantunut tai lähde on vaihtanut ratkaisun URL:ia. Tarkista, että
`state.json` on tallentunut repoon ajon jälkeen.

**Verohallinnon ohje ilmestyy uudelleen merkinnällä PÄIVITETTY.** Tämä on
tarkoituksellista. Vanha ohje voidaan päivittää, jolloin se nousee takaisin
vero.fi:n "Uusimmat"-lohkoon, ja käsin tehdyssä seurannassa tällainen ohje
raportoidaan uudelleen. KVL:n ennakkoratkaisuilla tätä ei tehdä, koska
ennakkoratkaisua ei päivitetä sisällöllisesti.
