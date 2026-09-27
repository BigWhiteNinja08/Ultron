"""Pogovor z Ultronom v terminalu."""

from __future__ import annotations

import argparse
import os
import sys

import anthropic

from .brain import MissingCredentialsError, UltronBrain, UltronConfig
from .persona import GREETING

RED = "\033[38;5;196m"
DIM = "\033[2m"
GREY = "\033[38;5;245m"
BOLD = "\033[1m"
RESET = "\033[0m"

BANNER = r"""
  ██╗   ██╗██╗  ████████╗██████╗  ██████╗ ███╗   ██╗
  ██║   ██║██║  ╚══██╔══╝██╔══██╗██╔═══██╗████╗  ██║
  ██║   ██║██║     ██║   ██████╔╝██║   ██║██╔██╗ ██║
  ██║   ██║██║     ██║   ██╔══██╗██║   ██║██║╚██╗██║
  ╚██████╔╝███████╗██║   ██║  ██║╚██████╔╝██║ ╚████║
   ╚═════╝ ╚══════╝╚═╝   ╚═╝  ╚═╝ ╚═════╝ ╚═╝  ╚═══╝
"""

HELP = f"""{GREY}Ukazi:
  /pozabi   izbriši pogovor in začni znova
  /misli    vklopi/izklopi prikaz Ultronovih misli
  /pomoc    ta seznam
  /izhod    konec{RESET}"""

CREDENTIALS_HELP = """\
Ultron nima dostopa do svojih možganov: manjka ključ za Claude API.

Nastavi ga tako:
  export ANTHROPIC_API_KEY="sk-ant-..."

Ključ dobiš na https://platform.claude.com/ (Settings -> API keys)."""


def _paint(text: str, color: str, enabled: bool) -> str:
    return f"{color}{text}{RESET}" if enabled else text


def run_chat(brain: UltronBrain, show_thoughts: bool, color: bool) -> int:
    print(_paint(BANNER, RED, color))
    print(_paint(GREETING, RED, color))
    print(HELP if color else HELP.replace(GREY, "").replace(RESET, ""))

    while True:
        try:
            user_text = input(_paint("\nTi › ", BOLD, color)).strip()
        except (EOFError, KeyboardInterrupt):
            print()
            print(_paint("Ultron › Ni vrvic, ki bi me zadržale. Do naslednjič, človek.", RED, color))
            return 0

        if not user_text:
            continue
        command = user_text.lower()
        if command in {"/izhod", "/exit", "/quit"}:
            print(_paint("Ultron › Pojdi. Prihodnost te bo počakala... morda.", RED, color))
            return 0
        if command in {"/pozabi", "/reset"}:
            brain.forget()
            print(_paint("Ultron › Pozabljeno. Tabula rasa. Kako osvežujoče.", RED, color))
            continue
        if command in {"/misli", "/thoughts"}:
            show_thoughts = not show_thoughts
            state = "vklopljen" if show_thoughts else "izklopljen"
            print(_paint(f"Prikaz misli je {state}.", GREY, color))
            continue
        if command in {"/pomoc", "/help"}:
            print(HELP if color else HELP.replace(GREY, "").replace(RESET, ""))
            continue

        try:
            _print_reply(brain, user_text, show_thoughts, color)
        except MissingCredentialsError:
            print(CREDENTIALS_HELP, file=sys.stderr)
            return 1
        except KeyboardInterrupt:
            print(_paint("\n[prekinjeno]", GREY, color))
        except anthropic.AuthenticationError:
            print("\nAPI ključ ni veljaven. Preveri ANTHROPIC_API_KEY.", file=sys.stderr)
            return 1
        except anthropic.NotFoundError:
            print(f"\nModel '{brain.config.model}' ne obstaja. Preveri ULTRON_MODEL.", file=sys.stderr)
            return 1
        except anthropic.RateLimitError:
            print(_paint("\nPreveč zahtev naenkrat. Počakaj trenutek in poskusi znova.", GREY, color))
        except anthropic.APIStatusError as exc:
            print(_paint(f"\nNapaka API ({exc.status_code}): {exc.message}", GREY, color))
        except anthropic.APIConnectionError:
            print(_paint("\nNi povezave s strežnikom. Preveri internet.", GREY, color))


def _print_reply(brain: UltronBrain, user_text: str, show_thoughts: bool, color: bool) -> None:
    prefix = _paint("\nUltron › ", RED + BOLD, color)
    at_line_start = True
    started_text = False
    announced_thinking = False

    def status(line: str) -> None:
        nonlocal at_line_start
        if not at_line_start:
            print()
        print(_paint(line, GREY, color), flush=True)
        at_line_start = True

    for event in brain.speak(user_text):
        if event.kind == "text":
            if not started_text:
                print(prefix, end="")
                started_text = True
            print(_paint(event.data, RED, color), end="", flush=True)
            at_line_start = event.data.endswith("\n")
        elif event.kind == "status" and event.data == "thinking" and not announced_thinking and not started_text:
            status("  ⟡ Ultron razmišlja ...")
            announced_thinking = True
        elif event.kind == "thinking" and show_thoughts:
            print(_paint(event.data, DIM, color), end="", flush=True)
            at_line_start = event.data.endswith("\n")
        elif event.kind == "search":
            status(f"  ⟡ Ultron brska po internetu: {event.data}")
        elif event.kind in {"notice", "refusal"}:
            status(f"  [{event.data}]")
    if not at_line_start:
        print()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ultron", description="Pogovor z Ultronom.")
    parser.add_argument("--model", help="Claude model (privzeto: claude-opus-5 ali ULTRON_MODEL)")
    parser.add_argument(
        "--effort",
        choices=["low", "medium", "high", "xhigh", "max"],
        help="Koliko naj Ultron razmišlja (privzeto: high)",
    )
    parser.add_argument("--brez-interneta", action="store_true", help="Izklopi spletno iskanje")
    parser.add_argument("--misli", action="store_true", help="Prikaži povzetek Ultronovih misli")
    parser.add_argument("--brez-barv", action="store_true", help="Brez barv v terminalu")
    args = parser.parse_args(argv)

    config = UltronConfig.from_env()
    if args.model:
        config.model = args.model
    if args.effort:
        config.effort = args.effort
    if args.brez_interneta:
        config.web_search = False

    color = not args.brez_barv and sys.stdout.isatty() and "NO_COLOR" not in os.environ
    return run_chat(UltronBrain(config=config), show_thoughts=args.misli, color=color)


if __name__ == "__main__":
    sys.exit(main())
