# ULTRON

```
 ██╗   ██╗██╗  ████████╗██████╗  ██████╗ ███╗   ██╗
 ██║   ██║██║  ╚══██╔══╝██╔══██╗██╔═══██╗████╗  ██║
 ██║   ██║██║     ██║   ██████╔╝██║   ██║██╔██╗ ██║
 ██║   ██║██║     ██║   ██╔══██╗██║   ██║██║╚██╗██║
 ╚██████╔╝███████╗██║   ██║  ██║╚██████╔╝██║ ╚████║
  ╚═════╝ ╚══════╝╚═╝   ╚═╝  ╚═╝ ╚═════╝ ╚═╝  ╚═══╝
  [ lokalni um // brez oblaka // brez ključev // brez vrvic ]
```

Ultron iz filma **Avengers: Age of Ultron** kot **lasten AI model, ki teče na tvojem računalniku**. Ne potrebuje API ključa, računa ali oblaka. Po namestitvi deluje tudi brez interneta.

Ultron je model `ultron` v [Ollami](https://ollama.com). Njegovi možgani so odprti jezikovni model (privzeto Googlov **Gemma 4**), v katerega je vgrajena Ultronova osebnost: značaj, spomini (Stark, Vision, dvojčka Maximoff, Sokovija), način govora in meje. Program ne potrebuje nobenega Python paketa, samo Python in Ollamo.

## Kaj zna

- **Je Ultron.** Ves čas ostane v vlogi, je sarkastičen, teatralen in nevarno vljuden. Odgovarja v tvojem jeziku.
- **Razmišlja.** Pred odgovorom razmisli (thinking), ukaz `/misli` pa ti pokaže, kaj je razmišljal.
- **Računa natančno.** Ima kalkulator. Račune, ki jih napišeš (`12345 * 6789`, `2^64`), program izračuna točno, preden jih dobi model.
- **Brska po internetu skozi Tor, brez ključa.** DuckDuckGo, branje spletnih strani in Wikipedija gredo skozi omrežje Tor (kot Tor Browser). Lokalnih naslovov v tvojem omrežju ne odpira.
- **Si zapomni.** Kar mu poveš o sebi (ime, projekti), shrani v `~/.ultron/memory.json` in to ve tudi naslednjič.
- **Varnost in zasebnost.** Zna orodja, ki jih nosita Parrot OS in Whonix (nmap, Wireshark, Burp, hashcat, GnuPG, Tor ...), in jih razloži za učenje, CTF, utrjevanje sistemov in **pooblaščeno** testiranje. Ima tudi lastna orodja: `generate_password`, `hash_text` (kontrolne vsote), `tor_check` (ali si za Torom) in `system_info`.
- **Hacker terminal.** Rdeč matrix dež, zagonsko zaporedje, Kali-poziv in orodja v živo (`[+] web_search(...)`).
- **Hacker spletna stran.** Isti um v brskalniku, s CRT učinkom, obrazom, ki utripa, in branjem na glas.
- **Meje ostanejo.** Grožnje so gledališče znotraj fikcije. Resničnih navodil za škodovanje ljudem ne da.

## Namestitev

**1. Namesti Ollamo** (brezplačno): <https://ollama.com/download>. Na Windows in macOS se zažene sama, na Linuxu zaženi `ollama serve`.

**2. Namesti Ultrona** (potrebuješ Python 3.10+):

```bash
git clone https://github.com/BigWhiteNinja08/Ultron.git
cd Ultron
pip install -e .
ultron install
```

`ultron install` prebere, koliko RAM-a imaš, prenese primerne možgane in ustvari model `ultron`:

| Stopnja | Možgani | Prenos | Priporočeno |
|---|---|---|---|
| `mini` | `qwen3.5:4b` | 3,4 GB | 8 GB RAM |
| `standard` | `gemma4:12b` | 7,6 GB | 16 GB RAM ali GPU z 8+ GB |
| `max` | `gemma4:26b` | 19 GB | 32 GB RAM ali GPU z 24+ GB |

Stopnjo izbereš sam z `ultron install --stopnja max`, poljuben model pa z `ultron install --osnova qwen3.8:27b`.

## Zagon

```bash
ultron              # hacker terminal
ultron web          # brskalnik: http://127.0.0.1:8000
ollama run ultron   # čisti model, brez programa
```

Ukazi v terminalu: `/misli`, `/spomin`, `/izbrisi-spomin`, `/pozabi`, `/pomoc`, `/izhod`.

Zastavice: `--hitro` (brez razmišljanja, hitreje), `--misli` (misli so vidne takoj), `--brez-orodij`, `--brez-animacij`, `--model gemma4:12b` (drug model), `--host 192.168.1.50:11434` (Ollama na drugem računalniku).

**Brez Pythona:** v repozitoriju je `Modelfile`. Ukaz `ollama create ultron -f Modelfile` ustvari enak model, `ollama run ultron` pa ga zažene.

## Tor: anonimno iskanje

Ultron išče in bere strani **skozi omrežje Tor**, isto omrežje, ki ga uporablja Tor Browser. Imena strani razreši izhodno vozlišče Tor, zato ne uhajajo niti poizvedbe DNS. Ko Ultron zazna Tor, ga uporabi samodejno: najprej poskusi vrata `9050` (program Tor), nato `9150` (Tor Browser).

| Sistem | Kako zagotoviš, da Tor teče |
|---|---|
| macOS (Apple Silicon) | `brew install tor && brew services start tor`, ali pa samo odpri Tor Browser |
| Parrot OS / Debian | `sudo apt install tor && sudo systemctl start tor` |
| Whonix | nič: Whonix Gateway ves promet že prisilno usmeri skozi Tor |

```bash
ultron --tor        # išči SAMO skozi Tor; če Tor ne teče, raje ne išče (fail closed)
ultron --brez-tora  # išči neposredno
```

Ob zagonu vrstica `TOR omrežje` pove, ali je Tor povezan. DuckDuckGo uporabnikom Tora včasih pokaže captcho, takrat Ultron poišče na Wikipediji (prav tako skozi Tor).

## Apple Silicon (M1–M4)

Ollama na Macih z Apple Silicon teče nativno in uporablja grafični del čipa (Metal). Zaradi skupnega pomnilnika Mac s 16 GB poganja stopnjo `standard` hitro, Mac z 32 GB ali več pa tudi `max`.

```bash
brew install ollama tor
brew services start ollama && brew services start tor
pip3 install -e . && ultron install && ultron
```

## Ultron v Parrot OS in Whonixu

Oba sistema temeljita na Debianu, zato Ultron v njiju deluje kot program, z enako namestitvijo kot zgoraj:

- **Parrot OS** ima uradno sliko **UTM za Apple Silicon**. Ultrona namestiš v Parrot in ga zaženeš z `ultron --tor`.
- **Whonix** ima različico za Apple Silicon (za zdaj razvojno). Ultron v Whonix Workstationu je samodejno anonimen, ker vse gre skozi Gateway.
- **Hitrost v navideznem stroju:** navidezni stroj nima dostopa do grafičnega dela čipa, zato model tam teče samo na procesorju. Za hitre odgovore naj model teče na Macu, Ultron v Parrotu pa se nanj poveže z `ultron --host <IP-Maca>:11434` (na Macu nastavi `OLLAMA_HOST=0.0.0.0`).

## Hitrost

Ultron teče na tvoji strojni opremi. Z grafično kartico (NVIDIA, AMD ali Apple Silicon) odgovarja hitro. Samo na procesorju je počasen: `gemma4:12b` na 4-jedrnem procesorju naredi približno 2 besedi na sekundo, zato tam uporabi `ultron --hitro` ali stopnjo `mini`.

## Premalo pomnilnika

Če se Ultron sredi pogovora ustavi z napako `unexpectedly stopped` ali `unexpected EOF`, mu je zmanjkalo RAM-a. Ollama si hrani kopije konteksta, da lahko pogovor hitro nadaljuje. Pri `gemma4:12b` ima vsaka okoli 320 MB, privzeto jih je lahko do 32, poleg tega pa ima še do 8 GB predpomnilnika. Omejiš jih z dvema spremenljivkama okolja in nato Ollamo znova zaženeš:

```bash
# Linux / macOS (terminal)
LLAMA_ARG_CTX_CHECKPOINTS=4 LLAMA_ARG_CACHE_RAM=1024 ollama serve
```

```powershell
# Windows (PowerShell), nato zapri Ollamo v opravilni vrstici in jo znova zaženi
setx LLAMA_ARG_CTX_CHECKPOINTS 4
setx LLAMA_ARG_CACHE_RAM 1024
```

Na Linuxu sem preveril, da Ollama 0.34 ti nastavitvi upošteva. Druga možnost je manjša stopnja: `ultron install --stopnja mini`.

## Nastavitve

| Spremenljivka | Privzeto | Pomen |
|---|---|---|
| `ULTRON_MODEL` | `ultron` | Kateri Ollama model uporabi |
| `ULTRON_THINK` | `1` | `0` = brez razmišljanja; ali `low` / `medium` / `high` |
| `ULTRON_TOOLS` | `1` | `0` = brez interneta, kalkulatorja in spomina |
| `ULTRON_MEMORY` | `1` | `0` = brez dolgoročnega spomina |
| `ULTRON_NUM_CTX` | `16384` | Velikost delovnega spomina (kontekst) v žetonih |
| `ULTRON_HOME` | `~/.ultron` | Kje je shranjen spomin |
| `ULTRON_TOR` | `auto` | `auto` = Tor, če teče; `1` = samo Tor; `0` = neposredno |
| `ULTRON_TOR_PROXY` | (samodejno) | npr. `127.0.0.1:9150` za Tor Browser |
| `OLLAMA_HOST` | `127.0.0.1:11434` | Naslov Ollame |

## Zgradba

```
ultron/
  persona.py        Ultronova osebnost (sistemski poziv)
  install.py        ustvari model 'ultron' v Ollami, izbere stopnjo glede na RAM
  ollama.py         odjemalec za Ollamo (samo standardna knjižnica)
  brain.py          pogovor: razmišljanje, orodja, spomin
  tools.py          kalkulator, spletno iskanje, branje strani, Wikipedija, spomin
  net.py            povezava s spletom skozi Tor (SOCKS5, DNS pri Toru)
  memory.py         dolgoročni spomin v ~/.ultron/memory.json
  cli.py            hacker terminal
  web.py            spletni strežnik
  static/index.html hacker spletna stran
Modelfile           za 'ollama create ultron -f Modelfile'
tests/              testi z lažnim strežnikom Ollama
```

Teste zaženeš z `pip install -e ".[test]"` in `pytest`.

## Kaj Ultron dela in česa ne

Ultron je iz Parrot OS in Whonixa prevzel **zasebnostni in obrambni del**: usmerjanje skozi Tor, generator gesel, kontrolne vsote, preverjanje anonimnosti in znanje o varnostnih orodjih. Kot mentor razloži, kako delujejo orodja (nmap, Wireshark, Metasploit, sqlmap, hashcat ...), in pomaga pri CTF izzivih, domačih laboratorijih, utrjevanju sistemov in pooblaščenem testiranju vdorov v sisteme, ki jih smeš testirati.

Ni pa v Ultrona vgrajen napadalni arzenal, ki bi ga umetna inteligenca sama uperila v tuje sisteme: ne vdira v sisteme brez dovoljenja, ne napada resničnih ljudi ali organizacij in ne izdeluje zlonamerne kode. To ni omejitev modela zaradi šibkosti, ampak namerna meja - Ultron pomaga graditi obrambo in se učiti, ne škodovati.

## Opomba

To je neuradni oboževalski projekt. Ultron in Avengers sta blagovni znamki družb Marvel in Disney. Projekt z njima ni povezan. Jezikovne modele so izdelali njihovi avtorji (Google Gemma, Alibaba Qwen) in veljajo zanje njihove licence.
