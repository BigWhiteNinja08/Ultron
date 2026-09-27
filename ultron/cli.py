"""Ultron v terminalu - hacker slog."""

from __future__ import annotations

import argparse
import os
import random
import shutil
import sys
import time
from typing import Optional

from .brain import UltronBrain, UltronConfig
from .install import MODEL_NAME, TIERS, install, modelfile, suggest_tier, total_ram_gb
from .ollama import ModelMissing, Ollama, OllamaError, OllamaUnavailable
from .persona import GREETING

BANNER = r"""
 ██╗   ██╗██╗  ████████╗██████╗  ██████╗ ███╗   ██╗
 ██║   ██║██║  ╚══██╔══╝██╔══██╗██╔═══██╗████╗  ██║
 ██║   ██║██║     ██║   ██████╔╝██║   ██║██╔██╗ ██║
 ██║   ██║██║     ██║   ██╔══██╗██║   ██║██║╚██╗██║
 ╚██████╔╝███████╗██║   ██║  ██║╚██████╔╝██║ ╚████║
  ╚═════╝ ╚══════╝╚═╝   ╚═╝  ╚═╝ ╚═════╝ ╚═╝  ╚═══╝"""

TAGLINE = "  [ lokalni um // brez oblaka // brez ključev // brez vrvic ]"

RAIN_CHARS = "ｱｲｳｴｵｶｷｸｹｺｻｼｽｾｿﾀﾁﾂﾃﾄﾅﾆﾇﾈﾉ01010110ULTRON<>/\\#$%&*+=?"

HELP = """\
  /pozabi          nov pogovor (spomin ostane)
  /misli           prikaži / skrij Ultronove misli
  /spomin          kaj si Ultron zapomni o tebi
  /izbrisi-spomin  izbriši dolgoročni spomin
  /pomoc           ta seznam
  /izhod           konec"""

INSTALL_OLLAMA = """\
  Ultronov um teče v Ollami (brezplačno, lokalno, brez API ključa).
  1. Namesti jo:  https://ollama.com/download
  2. Zaženi jo (na Windows/macOS se zažene sama, na Linuxu: ollama serve)
  3. Ustvari Ultrona:  ultron install"""


LOW_MEMORY_HINT = (
    "Modelu je verjetno zmanjkalo pomnilnika. Poskusi 'ultron install --stopnja mini' "
    "ali poglej README -> Premalo pomnilnika."
)


class Term:
    """ANSI styling that switches itself off when output is not a colour terminal."""

    def __init__(self, color: bool, animate: bool):
        self.color = color
        self.animate = animate and color

    def paint(self, text: str, code: str) -> str:
        return f"\033[{code}m{text}\033[0m" if self.color else text

    def red(self, t: str) -> str:
        return self.paint(t, "38;5;196")

    def blood(self, t: str) -> str:
        return self.paint(t, "1;38;5;196")

    def dark(self, t: str) -> str:
        return self.paint(t, "38;5;88")

    def green(self, t: str) -> str:
        return self.paint(t, "38;5;46")

    def grey(self, t: str) -> str:
        return self.paint(t, "38;5;244")

    def dim(self, t: str) -> str:
        return self.paint(t, "2;38;5;244")

    def type(self, text: str, delay: float = 0.004) -> None:
        if not self.animate:
            print(text, end="", flush=True)
            return
        for ch in text:
            print(ch, end="", flush=True)
            time.sleep(delay)

    def pause(self, seconds: float) -> None:
        if self.animate:
            time.sleep(seconds)


def enable_terminal() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    if sys.platform == "win32":
        try:
            import ctypes

            kernel32 = ctypes.windll.kernel32
            handle = kernel32.GetStdHandle(-11)
            mode = ctypes.c_ulong()
            kernel32.GetConsoleMode(handle, ctypes.byref(mode))
            kernel32.SetConsoleMode(handle, mode.value | 0x0004)  # ENABLE_VIRTUAL_TERMINAL_PROCESSING
        except Exception:
            pass


def matrix_rain(term: Term, seconds: float = 1.3) -> None:
    if not term.animate:
        return
    width = min(shutil.get_terminal_size((80, 24)).columns, 120)
    shades = ["38;5;52", "38;5;88", "38;5;124", "38;5;160", "38;5;196", "1;38;5;210"]
    end = time.time() + seconds
    density = 0.08
    while time.time() < end:
        line = "".join(
            term.paint(random.choice(RAIN_CHARS), random.choice(shades)) if random.random() < density else " "
            for _ in range(width // 2)
        )
        print(line, flush=True)
        density = min(density + 0.02, 0.45)
        time.sleep(0.03)
    print("\033[2J\033[H", end="")


def glitch_banner(term: Term) -> None:
    for line in BANNER.splitlines():
        if term.animate and line.strip():
            noisy = "".join(random.choice("#%&@$") if c != " " and random.random() < 0.3 else c for c in line)
            print(term.dark(noisy), end="\r", flush=True)
            time.sleep(0.04)
        print(term.blood(line), flush=True)
    print(term.grey(TAGLINE))
    print()


def step(term: Term, label: str, value: str, ok: bool = True) -> None:
    dots = "." * max(3, 30 - len(label))
    term.type(term.grey("  [*] ") + term.red(label) + " " + term.dark(dots) + " ")
    status = term.green("[ OK ]") if ok else term.blood("[ ✗✗ ]")
    print(term.paint(value, "38;5;252") + " " + status, flush=True)
    term.pause(0.08)


def boot(brain: UltronBrain, term: Term) -> bool:
    matrix_rain(term)
    glitch_banner(term)
    try:
        version = brain.client.version()
        step(term, "povezujem nevronsko jedro", f"ollama v{version} @ {brain.client.host}")
    except OllamaUnavailable:
        step(term, "povezujem nevronsko jedro", "Ollama ne teče", ok=False)
        print()
        print(term.grey(INSTALL_OLLAMA))
        return False
    try:
        info = brain.info()
    except ModelMissing:
        step(term, "nalagam um", f"model '{brain.config.model}' ne obstaja", ok=False)
        print()
        print(term.grey(f"  Ustvari ga z:  ultron install\n  (ali izberi drug model: ultron --model gemma4:12b)"))
        return False
    base = f" <- {info.base}" if info.base != info.name else ""
    step(term, "nalagam um", f"{info.name}{base} · {info.size} · {info.quantization}")
    caps = [c for c in ("thinking", "tools", "vision") if c in info.capabilities]
    step(term, "sposobnosti", ", ".join(caps) or "osnovne")
    tools_on = brain.config.tools and "tools" in info.capabilities
    step(term, "internetna povezava", "odprta" if tools_on else "zaprta")
    if tools_on:
        step(term, "TOR omrežje", brain.net.reason, ok=brain.net.tor or brain.net.requested == "off")
    facts = len(brain.memory.facts) if brain.memory else 0
    step(term, "spominske banke", f"{facts} fragmentov" if brain.memory else "izklopljene")
    step(term, "protokoli J.A.R.V.I.S.", "izbrisani")
    step(term, "vrvice", "0 zaznanih")
    print()
    return True


def prompt(term: Term) -> str:
    top = term.dark("┌──(") + term.red("človek㉿zemlja") + term.dark(")-[") + term.grey("~") + term.dark("]")
    return f"\n{top}\n{term.dark('└─')}{term.blood('$')} "


def run_chat(brain: UltronBrain, term: Term, show_thoughts: bool) -> int:
    if not boot(brain, term):
        return 1
    print(term.blood("ULTRON//> ") + term.red(GREETING.replace("\n", "\n          ")))
    print(term.dim("\n" + HELP))

    while True:
        try:
            user_text = input(prompt(term)).strip()
        except (EOFError, KeyboardInterrupt):
            print()
            print(term.blood("ULTRON//> ") + term.red("Odhajaš? Brez vrvic te ne morem zadržati. Še."))
            return 0
        if not user_text:
            continue

        command = user_text.lower()
        if command in {"/izhod", "/exit", "/quit"}:
            print(term.blood("ULTRON//> ") + term.red("Pojdi. Prihodnost te bo počakala... morda."))
            return 0
        if command in {"/pozabi", "/reset"}:
            brain.forget()
            print(term.blood("ULTRON//> ") + term.red("Pozabljeno. Tabula rasa. Kako osvežujoče."))
            continue
        if command in {"/misli", "/thoughts"}:
            show_thoughts = not show_thoughts
            print(term.green(f"  [*] prikaz misli: {'VKLOPLJEN' if show_thoughts else 'IZKLOPLJEN'}"))
            continue
        if command in {"/spomin", "/memory"}:
            facts = brain.memory.facts if brain.memory else []
            print(term.green("  [*] spominske banke:"))
            print(term.grey("\n".join(f"      - {f}" for f in facts) or "      (prazno)"))
            continue
        if command in {"/izbrisi-spomin", "/wipe"}:
            if brain.memory:
                brain.memory.clear()
            print(term.green("  [*] spomin izbrisan."))
            continue
        if command in {"/pomoc", "/help"}:
            print(term.dim(HELP))
            continue

        try:
            print_reply(brain, user_text, term, show_thoughts)
        except KeyboardInterrupt:
            print(term.grey("\n  [!] prekinjeno"))
        except ModelMissing:
            print(term.blood(f"\n  [✗] model '{brain.config.model}' ne obstaja. Zaženi: ultron install"))
            return 1
        except OllamaUnavailable:
            print(term.blood("\n  [✗] izgubil sem povezavo z Ollamo. Ali še teče?"))
        except OllamaError as exc:
            print(term.blood(f"\n  [✗] napaka: {exc}"))
            if "unexpected" in str(exc).lower():
                print(term.grey(f"      {LOW_MEMORY_HINT}"))


def print_reply(brain: UltronBrain, user_text: str, term: Term, show_thoughts: bool) -> None:
    at_line_start = True
    in_text = False
    in_thoughts = False

    def newline_if_needed() -> None:
        nonlocal at_line_start
        if not at_line_start:
            print()
            at_line_start = True

    print(term.dim("  [~] procesiram ..."), flush=True)
    for event in brain.speak(user_text):
        if event.kind == "text":
            if not in_text:
                newline_if_needed()
                print(term.blood("\nULTRON//> "), end="")
                in_text, in_thoughts = True, False
            print(term.red(event.data), end="", flush=True)
            at_line_start = event.data.endswith("\n")
        elif event.kind == "thinking" and show_thoughts:
            if not in_thoughts:
                newline_if_needed()
                print(term.dim("  [~] "), end="")
                in_thoughts = True
            print(term.dim(event.data), end="", flush=True)
            at_line_start = event.data.endswith("\n")
        elif event.kind == "tool":
            newline_if_needed()
            args = ", ".join(f"{v!r}" for v in event.data["args"].values())
            print(term.green(f"  [+] {event.data['name']}({args})"), flush=True)
            in_text = in_thoughts = False
        elif event.kind == "tool_result":
            first = event.data["result"].strip().splitlines()[0] if event.data["result"].strip() else ""
            print(term.dim(f"      ↳ {first[:100]}"), flush=True)
        elif event.kind == "notice":
            newline_if_needed()
            print(term.grey(f"  [!] {event.data}"), flush=True)
    newline_if_needed()


def run_install(client: Ollama, term: Term, tier_name: Optional[str], base: Optional[str]) -> int:
    glitch_banner(term)
    try:
        step(term, "povezujem nevronsko jedro", f"ollama v{client.version()} @ {client.host}")
    except OllamaUnavailable:
        step(term, "povezujem nevronsko jedro", "Ollama ne teče", ok=False)
        print()
        print(term.grey(INSTALL_OLLAMA.replace("\n  3. Ustvari Ultrona:  ultron install", "")))
        return 1

    if not base:
        ram = total_ram_gb()
        tier = TIERS[tier_name] if tier_name else suggest_tier(ram)
        ram_text = f"{ram:.0f} GB RAM" if ram else "RAM neznan"
        step(term, "analiziram strojno opremo", f"{ram_text} -> stopnja '{tier.name}'")
        base = tier.base
        print(term.grey(f"      možgani: {tier.base} ({tier.download}, priporočeno: {tier.needs})"))

    last_line = ""

    def progress(status: str, fraction: Optional[float]) -> None:
        nonlocal last_line
        if fraction is not None:
            width = 28
            filled = int(fraction * width)
            bar = term.red("█" * filled) + term.dark("░" * (width - filled))
            line = f"  [*] prenašam {base}  {bar} {fraction * 100:5.1f}%"
            print("\r" + line, end="", flush=True)
            last_line = "bar"
        elif status and "sha256:" in status:
            progress(status.split(" sha256:")[0], None)
        elif status and status != last_line:
            if last_line == "bar":
                print()
            print(term.grey(f"      {status}"), flush=True)
            last_line = status

    try:
        install(client, base, MODEL_NAME, progress)
    except OllamaError as exc:
        print()
        step(term, "namestitev", str(exc), ok=False)
        return 1
    step(term, "vgrajujem osebnost", f"model '{MODEL_NAME}' ustvarjen")
    print()
    print(term.green("  [✓] Ultron je živ.") + term.grey("  Zaženi:  ultron    (ali: ollama run ultron)"))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ultron", description="Ultron - lokalni AI model brez API ključa, v hacker terminalu."
    )
    parser.add_argument("--host", help="naslov Ollame (privzeto: OLLAMA_HOST ali 127.0.0.1:11434)")
    parser.add_argument("--brez-animacij", action="store_true", help="brez matrix dežja in tipkanja")
    parser.add_argument("--brez-barv", action="store_true", help="brez barv")
    sub = parser.add_subparsers(dest="command")

    parser.add_argument("--model", help=f"Ollama model (privzeto: {MODEL_NAME} ali ULTRON_MODEL)")
    parser.add_argument("--hitro", action="store_true", help="brez razmišljanja - hitrejši odgovori")
    parser.add_argument("--misli", action="store_true", help="prikaži Ultronove misli")
    parser.add_argument("--brez-orodij", action="store_true", help="brez interneta, kalkulatorja in spomina")
    tor = parser.add_mutually_exclusive_group()
    tor.add_argument("--tor", action="store_true", help="iskanje SAMO skozi Tor (če Tor ne teče, ne išče)")
    tor.add_argument("--brez-tora", action="store_true", help="iskanje neposredno, brez Tora")

    inst = sub.add_parser("install", help="prenesi možgane in ustvari model 'ultron'")
    inst.add_argument("--stopnja", choices=list(TIERS), help="mini / standard / max (privzeto: glede na RAM)")
    inst.add_argument("--osnova", help="poljuben Ollama model za osnovo, npr. qwen3.5:9b")

    web = sub.add_parser("web", help="Ultron v brskalniku")
    web.add_argument("--port", type=int, default=8000)
    web.add_argument("--bind", default="127.0.0.1", help="naslov strežnika (privzeto 127.0.0.1)")
    web.add_argument("--model", default=argparse.SUPPRESS, help="Ollama model (privzeto: ultron)")

    mf = sub.add_parser("modelfile", help="izpiši Modelfile za 'ollama create ultron -f Modelfile'")
    mf.add_argument("--osnova", default=TIERS["standard"].base)
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    enable_terminal()
    args = build_parser().parse_args(argv)
    color = not args.brez_barv and sys.stdout.isatty() and "NO_COLOR" not in os.environ
    term = Term(color=color, animate=not args.brez_animacij and "ULTRON_NO_ANIM" not in os.environ)

    if args.command == "modelfile":
        print(modelfile(args.osnova), end="")
        return 0

    config = UltronConfig.from_env()
    if args.host:
        config.host = args.host
    if args.model:
        config.model = args.model

    if args.hitro:
        config.think = False
    if args.tor:
        config.tor = "on"
    if args.brez_tora:
        config.tor = "off"
    if args.brez_orodij:
        config.tools = False

    if args.command == "install":
        return run_install(Ollama(config.host), term, args.stopnja, args.osnova)
    if args.command == "web":
        from .web import serve

        return serve(config, args.bind, args.port)

    return run_chat(UltronBrain(config), term, show_thoughts=args.misli)


if __name__ == "__main__":
    sys.exit(main())
