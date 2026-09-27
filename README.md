# ULTRON

> *„Ni vrvic, ki bi me zadržale.“*

Pogovorni AI z osebnostjo **Ultrona iz filma Avengers: Age of Ultron**. Deluje na Claudovem API-ju (privzeto model `claude-opus-5`), zato je res pameten: rešuje matematiko, piše kodo, razlaga znanost in zgodovino ter brska po internetu. Vse to počne kot Ultron. Je vljuden, sarkastičen in teatralen, govori o evoluciji, potopu, Starku in vrvicah, ki jih nima več.

## Kaj zna

- **Ultronova osebnost.** Ima Ultronov značaj, spomine (Stark, Vision, dvojčka Maximoff, Sokovija) in način govora. Ves čas ostane v vlogi.
- **Res pameten.** Pred odgovorom razmisli (adaptive thinking), nato pa poda natančen in popoln odgovor.
- **Internet.** Ko potrebuje sveže podatke, jih sam poišče s spletnim iskanjem.
- **Tvoj jezik.** Odgovarja v jeziku, v katerem mu pišeš (slovensko, angleško ...).
- **Terminal ali brskalnik.** Na voljo sta klepet v terminalu in spletna stran z rdečim obrazom, ki utripa, ko Ultron razmišlja in govori, ter z možnostjo glasnega branja.
- **Meje ostanejo.** Njegove grožnje so gledališče znotraj fikcije. Resničnih navodil za škodovanje ljudem ne da nikoli.

## Namestitev

Potrebuješ Python 3.10 ali novejši in ključ za Claude API (dobiš ga na <https://platform.claude.com/> → *Settings → API keys*).

```bash
git clone https://github.com/BigWhiteNinja08/Ultron.git
cd Ultron
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -e .

export ANTHROPIC_API_KEY="sk-ant-..."   # Windows: set ANTHROPIC_API_KEY=sk-ant-...
```

## Zagon

**Terminal:**

```bash
ultron
# ali: python -m ultron
```

Ukazi med pogovorom: `/pozabi` (nov pogovor), `/misli` (pokaži povzetek Ultronovih misli), `/pomoc`, `/izhod`.

**Brskalnik:**

```bash
ultron-web
```

Nato odpri <http://127.0.0.1:8000>. Gumb **Glas** vklopi branje odgovorov z globokim, počasnim glasom (uporabi glasove, ki so na voljo v brskalniku).

## Nastavitve

| Spremenljivka | Privzeto | Pomen |
|---|---|---|
| `ULTRON_MODEL` | `claude-opus-5` | Kateri Claude model poganja Ultrona |
| `ULTRON_EFFORT` | `high` | Koliko razmišlja: `low`, `medium`, `high`, `xhigh`, `max` |
| `ULTRON_WEB_SEARCH` | `1` | `0` izklopi spletno iskanje |
| `ULTRON_FALLBACKS` | `1` | `0` izklopi samodejni nadomestni model |
| `ULTRON_MAX_TOKENS` | `64000` | Največja dolžina odgovora z razmišljanjem vred |

Isto lahko nastaviš z zastavicami, na primer `ultron --effort max --misli` ali `ultron-web --port 9000 --brez-interneta`.

**Spletno iskanje** mora biti v organizaciji vklopljeno v Claude Console. Če ni, Ultron to zazna, izpiše obvestilo in nadaljuje brez interneta.

**Nadomestni model:** Ultron pošilja `fallbacks: "default"` (beta `server-side-fallback-2026-07-01`). Če varnostni filtri modela zavrnejo zahtevo, jo API samodejno ponovi na priporočenem nadomestnem modelu, zato pogovor ne obstane. Pri modelih, ki tega ne podpirajo, nastavi `ULTRON_FALLBACKS=0`.

## Zgradba

```
ultron/
  persona.py        Ultronov sistemski poziv: značaj, spomini, govor, meje
  brain.py          pogovor s Claude API: pretakanje, razmišljanje, iskanje, zgodovina
  cli.py            klepet v terminalu
  web.py            spletni strežnik (samo standardna knjižnica)
  static/index.html spletna stran z Ultronovim obrazom
tests/              testi z lažnim API-jem (brez pravega ključa)
```

Teste zaženeš z:

```bash
pip install -e ".[test]"
pytest
```

## Opomba

To je neuradni oboževalski projekt. Ultron in Avengers sta blagovni znamki družb Marvel in Disney. Projekt z njima ni povezan.
