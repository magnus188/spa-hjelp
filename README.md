# Spa-hjelp

En liten, lokal kalkulator for ett Sundance-massasjebad og SpaCare-produktene i
Sundances norske vannpleierutine. Grensesnittet er laget for en 10-tommers
berøringsskjerm i Home Assistant, men fungerer også på mobil.

## Dette gjør appen

- Lagrer vannvolum, måleskje per produkt, manuelle målinger og tilsetningshistorikk i SQLite.
  Teststrips kan registreres med pH, alkalinitet, fritt klor og O₂ (aktivt oksygen)
  hver for seg. Siste verdi og måletidspunkt beholdes for hvert felt.
- Viser ett neste steg for nytt vann, ukentlig stell, før/etter bad og ferie.
- Regner om doser til ml og antall egne skjeer. Faste Sundance-doser er basert på
  **15 ml per Sundance-skje**, også når din egen skje har en annen størrelse.
- Viser et teoretisk MiniChlor-estimat for ønsket klorøkning, inkludert små
  skjeandeler, med beskjed om å måle igjen.
- Starter 20 minutters «hold lokket åpent»-timer etter registrert
  kjemikalietilsetning. Timeren lagres i databasen og fortsetter etter omstart.
- Tilbyr et kompakt `/card` for Home Assistant og en JSON-oppsummering på
  `/api/summary`.

Appen styrer ikke badets pumper eller temperatur. Den avgjør heller ikke om
vannet er klart for bading.
O₂-verdien loggføres, men brukes foreløpig ikke til å beregne en dose.

## Bruk rett i nettleseren

[GitHub Pages-utgaven](https://magnus188.github.io/spa-hjelp/) har samme
skjema, rutiner, doseberegninger og lokk-timer uten server. Målinger,
innstillinger og tilsetninger lagres i `localStorage` på denne nettleseren. De
overlever sideoppdatering, omstart og nye versjoner av nettsiden, men deles
ikke med hjemmeserverens SQLite-database, Home Assistant eller PoolLab, og kan
forsvinne hvis nettleserdata slettes. En annen enhet har egne data.

Nye installasjoner starter med 1500 liter. En tidligere lagret verdi beholdes.
I «Juster verdier» kan du velge økning for alkalinitet, pH, fritt klor og O₂.
Veiviseren følger alkalinitet → pH → MiniChlor → pumpesyklus → Active Oxygen,
med ny måling mellom trinnene. SpaCare oppgir ingen pålitelig omregning fra
Active Oxygen Granular til en bestemt målt O₂-økning. Derfor brukes Sundances
før-bad-dose når O₂ er valgt, og verdien må kontrolleres etterpå.

De statiske filene i `docs/` bygges fra Flask-malen og appens produktliste med:

```bash
python3 scripts/build_pages.py
node tests/pages-api.test.mjs
```

GitHub Pages publiserer `docs/` fra `main`.

## Start lokalt

Krever Python 3.12 eller nyere.

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
SPA_DB_PATH=./data/spa.sqlite3 PORT=8080 .venv/bin/python app.py
```

Åpne `http://localhost:8080/`. Kjør testene med:

```bash
.venv/bin/python -m unittest discover -s tests -v
```

I Docker bygges bildet med `docker build -t spa-hjelp:local .`. Sett
`SPA_DB_PATH=/data/spa.sqlite3` og monter en skrivbar mappe på `/data`.
GitHub Actions bygger `linux/arm64` og `linux/amd64` til GHCR ved push til `main`
etter at prosjektet er publisert på GitHub.

## Dosekilder og grenser

Rutinen kommer fra [Sundance Norges guide](https://www.sundance.no/vannpleie-med-sunpurity-og-active-oxygen/).
Der guiden ikke angir mengde, brukes produktets SpaCare-bruksanvisning.
Ukentlig, ved nypåfylling og ved ferie er MiniChlor **2 × 15 ml**, uavhengig av
vannvolum. Active Oxygen før bad er minst **3 × 15 ml**, med én ekstra skje per
person over tre. No Scale og OxyPlus skaleres med volum.

Etter bad viser appen [SpaCare MiniChlors](https://scandinavianspacare.no/wp-content/uploads/2017/10/Bruksanvisning-for-SpaCare-MiniChlor.pdf)
etikettdose på 5 ml per 1000 liter som et startestimat. Sundance beskriver
behovet som avhengig av bruk og ber om ny måling neste dag. pH og alkalinitet
justeres i små, etikettbaserte trinn før ny måling. [Alka Down har en egen
instruks](https://scandinavianspacare.no/wp-content/uploads/2017/10/Bruksanvisning-for-SpaCare-Alka-Down-1.pdf)
om pumpen av i én time; den vises på det aktuelle steget.

Klorøkning beregnes idealisert fra MiniChlors innhold av
[troclosennatrium-dihydrat](https://www.sundance.no/wp-content/uploads/2022/08/SpaCareMinichlor_NO.pdf)
(omtrent 55 % tilgjengelig klor) og produktets 1 g ≈ 1 ml på etiketten.
Formelen er `økning_mg/L × vann_L / (1000 × 0,55)` ml. Reelt klorforbruk i vannet
er ukjent. Derfor rundes små doser aldri opp til en hel skje, og appen ber om ny
måling etterpå.

Ved ferie brukes Sundances faste rekkefølge: mål vannet, kontroller filteret,
MiniChlor 30 ml, vent minst 5 minutter med pumpene på, deretter OxyPlus
20 ml/1000 liter og vurder ca. 28 °C. Antall feriedager øker ikke dosen.

Etter tilsetning viser appen 20 minutters åpent lokk for å la kjemisk damp
slippe ut, slik [Sundance-manualen](https://www.sundance.no/wp-content/uploads/2022/09/880-Brukermanmanual-2021.pdf)
beskriver. MiniChlor og Active Oxygen kan ikke bekreftes innen samme
20-minutters sirkulasjonssyklus.

## Home Assistant

Appen og HA må nå hverandre over hjemmenettet. Legg appen på en LAN-port og bruk
`/card` som Webpage-kort på oversikten. Bruk `/` som egen Webpage-visning.
`GET /api/summary` er for HA REST-sensorer. Homeserver-oppsettet i søsterrepoet
inneholder YAML-filene og en konkret installasjonsoppskrift.

Appen har ingen innlogging og er ment for et betrodd hjemmenett. Gi den ikke en
offentlig rute uten å legge til tilgangskontroll.

## PoolLab 2.0

Første versjon bruker manuelle målinger. Neste trinn er en lesende import via
[LabCOM API](https://www.primelab.org/labcom-cloud), med token på serveren og
kilde/tidspunkt på hver importert måling. Manuell registrering blir værende.

## Lisens

MIT. Se [LICENSE](LICENSE) og [THIRD_PARTY.md](THIRD_PARTY.md).
