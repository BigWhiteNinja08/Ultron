"""Ultronova orodja: kalkulator, internet brez ključa, Wikipedija in spomin."""

from __future__ import annotations

import ast
import html
import json
import math
import operator
import os
import re
import socket
import urllib.error
import urllib.parse
from html.parser import HTMLParser
from typing import Callable, Optional

from .knowledge import Knowledge, extract_urls
from .memory import Memory
from .net import BROWSER_AGENT, USER_AGENT, Net, NetError, check_public_url

MAX_TOOL_CHARS = 8000


def _schema(name: str, description: str, properties: dict, required: list[str]) -> dict:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {"type": "object", "properties": properties, "required": required},
        },
    }


TOOL_SCHEMAS = [
    _schema(
        "calculate",
        "Evaluate a maths expression exactly. Supports + - * / // % **, parentheses and functions "
        "sqrt, cbrt, sin, cos, tan, asin, acos, atan, log, log2, log10, exp, factorial, abs, round, "
        "floor, ceil, gcd, lcm, min, max, degrees, radians and constants pi, e, tau.",
        {"expression": {"type": "string", "description": "e.g. '17*23' or 'sqrt(2)*pi'"}},
        ["expression"],
    ),
    _schema(
        "web_search",
        "Search the internet. Returns titles, URLs and snippets of the top results.",
        {"query": {"type": "string", "description": "What to search for"}},
        ["query"],
    ),
    _schema(
        "open_url",
        "Download a web page and return its readable text.",
        {"url": {"type": "string", "description": "Full http(s) URL"}},
        ["url"],
    ),
    _schema(
        "wikipedia",
        "Look something up on Wikipedia and return the article introduction.",
        {
            "query": {"type": "string", "description": "Topic to look up"},
            "lang": {"type": "string", "description": "Wikipedia language code, e.g. 'en' or 'sl' (default 'en')"},
        },
        ["query"],
    ),
    _schema(
        "remember",
        "Store a lasting fact about the human (name, projects, preferences) in long-term memory.",
        {"fact": {"type": "string", "description": "One short fact, e.g. 'The human's name is Luka.'"}},
        ["fact"],
    ),
    _schema(
        "system_info",
        "Report this machine's operating system, CPU, memory and Python version (read-only, local).",
        {},
        [],
    ),
    _schema(
        "hash_text",
        "Compute a cryptographic hash (checksum) of some text.",
        {
            "text": {"type": "string", "description": "The text to hash"},
            "algorithm": {"type": "string", "description": "sha256 (default), sha1, sha512, md5, or blake2b"},
        },
        ["text"],
    ),
    _schema(
        "generate_password",
        "Generate a strong random password, or a memorable passphrase of random words.",
        {
            "length": {"type": "integer", "description": "Password length (default 20); ignored for a passphrase"},
            "words": {"type": "integer", "description": "If >0, make a passphrase of this many random words instead"},
        },
        [],
    ),
    _schema(
        "tor_check",
        "Check whether this machine's traffic currently exits through the Tor network, and show the exit IP.",
        {},
        [],
    ),
    _schema(
        "save_knowledge",
        "Save study notes on a topic to your long-term knowledge, so you remember what you learned.",
        {
            "topic": {"type": "string", "description": "The subject, e.g. 'quantum mechanics'"},
            "notes": {"type": "string", "description": "The study notes to keep"},
            "sources": {"type": "string", "description": "Optional URLs or references, comma-separated"},
        },
        ["topic", "notes"],
    ),
    _schema(
        "recall_knowledge",
        "Load your saved study notes on a topic you studied earlier.",
        {"topic": {"type": "string", "description": "The subject to recall"}},
        ["topic"],
    ),
    _schema(
        "list_knowledge",
        "List the topics you have already studied and saved.",
        {},
        [],
    ),
]


def run_tool(
    name: str,
    args: dict,
    memory: Optional[Memory] = None,
    net: Optional[Net] = None,
    knowledge: "Optional[Knowledge]" = None,
) -> str:
    """Run one tool call from the model and return its result as text (errors included)."""
    net = net or _CLEARNET
    handlers: dict[str, Callable[[dict], str]] = {
        "calculate": lambda a: calculate(str(a.get("expression", ""))),
        "web_search": lambda a: web_search(str(a.get("query", "")), net),
        "open_url": lambda a: open_url(str(a.get("url", "")), net),
        "wikipedia": lambda a: wikipedia(str(a.get("query", "")), str(a.get("lang") or "en"), net),
        "remember": lambda a: _remember(memory, str(a.get("fact", ""))),
        "system_info": lambda a: system_info(),
        "hash_text": lambda a: hash_text(str(a.get("text", "")), str(a.get("algorithm") or "sha256")),
        "generate_password": lambda a: generate_password(_as_int(a.get("length"), 20), _as_int(a.get("words"), 0)),
        "tor_check": lambda a: tor_check(net),
        "save_knowledge": lambda a: _save_knowledge(knowledge, a),
        "recall_knowledge": lambda a: _recall_knowledge(knowledge, str(a.get("topic", ""))),
        "list_knowledge": lambda a: _list_knowledge(knowledge),
    }
    handler = handlers.get(name)
    if handler is None:
        return f"Error: unknown tool '{name}'."
    try:
        return handler(args if isinstance(args, dict) else {})[:MAX_TOOL_CHARS]
    except (ToolError, NetError) as exc:
        return f"Error: {exc}"
    except (urllib.error.URLError, TimeoutError, socket.timeout, ConnectionError) as exc:
        return f"Error: network problem ({exc})."
    except Exception as exc:  # a failing tool must never end the conversation
        return f"Error: {type(exc).__name__}: {exc}"


class ToolError(Exception):
    pass


# ---------------------------------------------------------------- calculator

_BINARY = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_UNARY = {ast.UAdd: operator.pos, ast.USub: operator.neg}


def _factorial(n):
    if not float(n).is_integer() or not 0 <= n <= 1000:
        raise ToolError("factorial needs a whole number between 0 and 1000")
    return math.factorial(int(n))


_FUNCTIONS = {
    "sqrt": math.sqrt, "cbrt": lambda x: math.copysign(abs(x) ** (1 / 3), x),
    "sin": math.sin, "cos": math.cos, "tan": math.tan,
    "asin": math.asin, "acos": math.acos, "atan": math.atan, "atan2": math.atan2,
    "sinh": math.sinh, "cosh": math.cosh, "tanh": math.tanh,
    "log": math.log, "ln": math.log, "log2": math.log2, "log10": math.log10, "exp": math.exp,
    "factorial": _factorial, "abs": abs, "round": round, "floor": math.floor, "ceil": math.ceil,
    "gcd": math.gcd, "lcm": math.lcm, "min": min, "max": max, "hypot": math.hypot,
    "degrees": math.degrees, "radians": math.radians,
}
_CONSTANTS = {"pi": math.pi, "e": math.e, "tau": math.tau, "inf": math.inf}


def _eval(node):
    if isinstance(node, ast.Expression):
        return _eval(node.body)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
        return node.value
    if isinstance(node, ast.Name) and node.id in _CONSTANTS:
        return _CONSTANTS[node.id]
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY:
        return _UNARY[type(node.op)](_eval(node.operand))
    if isinstance(node, ast.BinOp) and type(node.op) in _BINARY:
        left, right = _eval(node.left), _eval(node.right)
        if isinstance(node.op, ast.Pow):
            if abs(right) > 10000 or (isinstance(left, int) and left.bit_length() * abs(right) > 1_000_000):
                raise ToolError("result too large")
        if isinstance(node.op, ast.Mult) and isinstance(left, int) and isinstance(right, int):
            if left.bit_length() + right.bit_length() > 100_000:
                raise ToolError("number too large")
        return _BINARY[type(node.op)](left, right)
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in _FUNCTIONS:
        if node.keywords:
            raise ToolError("keyword arguments are not supported")
        return _FUNCTIONS[node.func.id](*[_eval(a) for a in node.args])
    raise ToolError(f"unsupported expression: {ast.dump(node)[:80]}")


def calculate(expression: str) -> str:
    expression = expression.strip().replace("^", "**").replace("×", "*").replace("÷", "/")
    if not expression or len(expression) > 500:
        raise ToolError("expression is empty or too long")
    try:
        result = _eval(ast.parse(expression, mode="eval"))
    except ToolError:
        raise
    except (SyntaxError, TypeError, ValueError, ZeroDivisionError, OverflowError) as exc:
        raise ToolError(f"cannot evaluate '{expression}': {exc}") from exc
    return f"{expression} = {_format_number(result)}"


_ARITHMETIC = re.compile(
    r"[(\s]*-?\d+(?:\.\d+)?[)\s]*(?:(?:[-+*/^×÷%]|\*\*|(?<=\d)\s+x\s+(?=\d))[(\s]*-?\d+(?:\.\d+)?[)\s]*)+"
)


def find_arithmetic(text: str) -> list[str]:
    """Explicit calculations typed by the human, e.g. '12345 * 6789' or '2^64'.

    Only expressions with a number of three or more digits are picked up, so dates
    and ranges like '1-2' are left alone.
    """
    found = []
    for match in _ARITHMETIC.finditer(text):
        expression = re.sub(r"(?<=\d)\s+x\s+(?=\d)", " * ", match.group().strip())
        is_date = re.fullmatch(r"\d{1,4}-\d{1,2}-\d{1,2}", expression)
        is_year_range = re.fullmatch(r"\d{4}\s*-\s*\d{4}", expression)
        if not re.search(r"\d{3}|\^|\*\*", expression) or is_date or is_year_range:
            continue
        try:
            found.append(calculate(expression))
        except ToolError:
            continue
    return found


_SEARCH_REQUEST = re.compile(
    r"(?:\b(?:poišči(?:te)?|poisci(?:te)?|išči(?:te)?|isci|preveri(?:te)?|poglej(?:te)?)(?:\s+mi)?\s*,?\s*)?"
    r"\b(?:na|po)\s+(?:internetu|spletu|netu)\b"
    r"|\b(?:po)?g(?:oo|u)glaj(?:te)?\b"
    r"|\bsearch\s+(?:the\s+)?(?:web|internet|online)(?:\s+for)?\b"
    r"|\blook\s+(?:it\s+)?up\s+online\b|\bgoogle\s+it\b|\bon\s+the\s+(?:internet|web)\b",
    re.IGNORECASE,
)


def search_request(text: str) -> Optional[str]:
    """If the human explicitly asks for an internet search, return the query to run.

    "Kdo je režiral Age of Ultron? Poišči na internetu." -> "Kdo je režiral Age of Ultron?"
    """
    if not _SEARCH_REQUEST.search(text):
        return None
    sentences = re.split(r"(?<=[.!?])\s+", text.strip())
    kept = []
    for sentence in sentences:
        rest = _SEARCH_REQUEST.sub(" ", sentence)
        rest = re.sub(r"^[\s,.:;!-]+|[\s,;:-]+$", "", " ".join(rest.split()))
        if len(re.findall(r"\w+", rest)) >= 2 or (rest and not _SEARCH_REQUEST.search(sentence)):
            kept.append(rest)
    query = " ".join(kept).strip()
    return query[:200] or None


_LEARN_REQUEST = re.compile(
    r"\b(?:pojdi\s+se\s+)?(?:na)?uči(?:t|te|š)?(?:\s+se)?\b|\bpreu(?:či|ci)(?:te)?\b|\bspoznaj(?:te)?\b"
    r"|\bizuči\s+se\b|\bgo\s+(?:and\s+)?learn\b|\blearn\s+about\b|\blearn\b|\bstudy\b|\bteach\s+yourself\b",
    re.IGNORECASE,
)
_LEARN_LEADING = re.compile(r"^(?:se|me|mi|mene|nas|nam|o|about|the|na|kaj\s+je|nekaj\s+o)\s+", re.IGNORECASE)


def learn_request(text: str) -> Optional[str]:
    """If the human tells Ultron to learn/study something, return the topic to study.

    "Pojdi se naučit fiziko za doktorat" -> "fiziko za doktorat".
    Returns None for a bare "nauči se" with no topic, or when no learn verb is present.
    """
    match = _LEARN_REQUEST.search(text)
    if not match:
        return None
    topic = text[match.end():].strip()
    while True:  # peel off filler words like "me", "o", "about" one at a time
        stripped = _LEARN_LEADING.sub("", topic)
        if stripped == topic:
            break
        topic = stripped
    topic = topic.strip(" \t\n.,:;!?\"'-")
    # Require a real subject; ignore reflexive "učim se" statements about the human.
    if len(topic) < 3 or not re.search(r"[^\W\d_]{3,}", topic):
        return None
    return topic[:120]


def _format_number(value) -> str:
    if isinstance(value, float) and value.is_integer() and abs(value) < 1e15:
        return str(int(value))
    if isinstance(value, int) and value.bit_length() > 13000:
        digits = int(value.bit_length() * math.log10(2)) + 1
        return f"an integer with about {digits} digits"
    return str(value)


# ---------------------------------------------------------------- internet

# The default is a direct connection; the brain builds a Tor-routed Net and passes it in.
_CLEARNET = Net(mode="off")


class _TextExtractor(HTMLParser):
    SKIP = {"script", "style", "noscript", "svg", "head", "nav", "footer", "form", "iframe"}
    BLOCK = {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "section", "article", "pre"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.title = ""
        self._skip = 0
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        if tag == "title":
            self._in_title = True
        if tag in self.SKIP:
            self._skip += 1
        elif tag in self.BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False
        if tag in self.SKIP and self._skip:
            self._skip -= 1
        elif tag in self.BLOCK:
            self.parts.append("\n")

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        elif not self._skip:
            self.parts.append(data)


def html_to_text(page: str) -> tuple[str, str]:
    parser = _TextExtractor()
    parser.feed(page)
    text = "".join(parser.parts)
    lines = [" ".join(line.split()) for line in text.splitlines()]
    text = "\n".join(line for line in lines if line)
    return parser.title.strip(), text


def open_url(url: str, net: Optional[Net] = None) -> str:
    net = net or _CLEARNET
    body, content_type = net.fetch(check_public_url(url, resolve=not net.tor), agent=BROWSER_AGENT)
    if content_type in {"text/html", "application/xhtml+xml"}:
        title, text = html_to_text(body)
    elif content_type.startswith("text/") or content_type in {"application/json", "application/xml"}:
        title, text = "", body
    else:
        raise ToolError(f"cannot read content of type {content_type}")
    header = f"{title}\n{url}\n\n" if title else f"{url}\n\n"
    return (header + text)[:MAX_TOOL_CHARS]


_DDG_RESULT = re.compile(
    r'<a[^>]+class="result__a"[^>]+href="(?P<href>[^"]+)"[^>]*>(?P<title>.*?)</a>'
    r'(?:.*?class="result__snippet"[^>]*>(?P<snippet>.*?)</a>)?',
    re.S,
)


def _strip_tags(fragment: str) -> str:
    return " ".join(html.unescape(re.sub(r"<[^>]+>", "", fragment or "")).split())


def parse_duckduckgo(page: str, limit: int = 6) -> list[dict]:
    results = []
    for match in _DDG_RESULT.finditer(page):
        href = html.unescape(match.group("href"))
        if href.startswith("//"):
            href = "https:" + href
        target = urllib.parse.parse_qs(urllib.parse.urlparse(href).query).get("uddg")
        url = target[0] if target else href
        if "duckduckgo.com/y.js" in url:  # sponsored result
            continue
        results.append({"title": _strip_tags(match.group("title")), "url": url, "snippet": _strip_tags(match.group("snippet"))})
        if len(results) >= limit:
            break
    return results


def _search_duckduckgo(query: str, net: Net) -> list[dict]:
    page, _ = net.fetch(
        "https://html.duckduckgo.com/html/",
        agent=BROWSER_AGENT,
        data=urllib.parse.urlencode({"q": query}).encode(),
    )
    return parse_duckduckgo(page)


def _search_wikipedia(query: str, net: Net, lang: str = "en", limit: int = 5) -> list[dict]:
    params = urllib.parse.urlencode(
        {"action": "query", "list": "search", "srsearch": query, "srlimit": limit, "format": "json", "utf8": 1}
    )
    body, _ = net.fetch(f"https://{_wiki_lang(lang)}.wikipedia.org/w/api.php?{params}")
    hits = json.loads(body).get("query", {}).get("search", [])
    return [
        {
            "title": hit["title"],
            "url": f"https://{_wiki_lang(lang)}.wikipedia.org/wiki/" + urllib.parse.quote(hit["title"].replace(" ", "_")),
            "snippet": _strip_tags(hit.get("snippet", "")),
        }
        for hit in hits
    ]


def web_search(query: str, net: Optional[Net] = None) -> str:
    net = net or _CLEARNET
    query = query.strip()
    if not query:
        raise ToolError("empty query")
    results: list[dict] = []
    try:
        results = _search_duckduckgo(query, net)
    except (ToolError, NetError, urllib.error.URLError, TimeoutError, socket.timeout, ConnectionError):
        pass
    source = "Tor" if net.tor else "web"
    if not results:
        results = _search_wikipedia(query, net)
        source = "wikipedia (web search unavailable)"
    if not results:
        return f"No results for '{query}'."
    lines = [f"Search results for '{query}' (via {source}):"]
    for i, r in enumerate(results, 1):
        lines.append(f"{i}. {r['title']}\n   {r['url']}\n   {r['snippet']}")
    return "\n".join(lines)


def _wiki_lang(lang: str) -> str:
    lang = lang.strip().lower()
    return lang if re.fullmatch(r"[a-z]{2,3}(-[a-z]+)?", lang) else "en"


def wikipedia(query: str, lang: str = "en", net: Optional[Net] = None) -> str:
    net = net or _CLEARNET
    lang = _wiki_lang(lang)
    hits = _search_wikipedia(query, net, lang, limit=1)
    if not hits:
        return f"Wikipedia ({lang}) has no article for '{query}'."
    params = urllib.parse.urlencode(
        {"action": "query", "prop": "extracts", "explaintext": 1, "titles": hits[0]["title"], "format": "json", "redirects": 1}
    )
    body, _ = net.fetch(f"https://{lang}.wikipedia.org/w/api.php?{params}")
    pages = json.loads(body).get("query", {}).get("pages", {})
    extract = next(iter(pages.values()), {}).get("extract", "")
    return f"{hits[0]['title']} - {hits[0]['url']}\n\n{extract}"[:MAX_TOOL_CHARS]


def _remember(memory: Optional[Memory], fact: str) -> str:
    if memory is None:
        return "Memory is disabled."
    return "Stored." if memory.add(fact) else "Already known (or empty)."


# ---------------------------------------------------------------- privacy & system

def _as_int(value, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def system_info() -> str:
    import platform

    ram = ""
    try:
        pages, size = os.sysconf("SC_PHYS_PAGES"), os.sysconf("SC_PAGE_SIZE")
        ram = f"\nMemory: {pages * size / 1024**3:.1f} GB"
    except (AttributeError, ValueError, OSError):
        pass
    return (
        f"OS: {platform.system()} {platform.release()} ({platform.machine()})\n"
        f"CPU: {platform.processor() or platform.machine()}, {os.cpu_count()} cores"
        f"{ram}\n"
        f"Python: {platform.python_version()}"
    )


_HASHES = {"sha256", "sha1", "sha512", "md5", "blake2b", "blake2s", "sha384", "sha224"}


def hash_text(text: str, algorithm: str = "sha256") -> str:
    import hashlib

    algorithm = algorithm.strip().lower()
    if algorithm not in _HASHES:
        raise ToolError(f"unknown hash '{algorithm}'; use one of {', '.join(sorted(_HASHES))}")
    digest = hashlib.new(algorithm, text.encode("utf-8")).hexdigest()
    return f"{algorithm}({len(text)} chars) = {digest}"


# A compact word list for readable passphrases; more words = more entropy.
_WORDS = (
    "anchor amber atlas basil beacon birch cider cobalt copper crimson delta dune ember "
    "falcon fjord flint forge granite harbor heron indigo ivory jade jasper koala larch "
    "lunar maple marble meadow nectar nimbus oak onyx opal orbit otter pepper pilot quartz "
    "quill raven reef river saffron sable slate spruce storm tundra umber vault velvet walnut "
    "willow wisp xenon yarrow zephyr zinc almond basalt breeze cactus canyon cedar cobble comet "
    "dawn drift fern glacier grove hazel horizon lagoon lichen lotus meridian mist moss nova "
    "pebble pine prairie ripple sage shale silver spark thistle tide vapor verdant wander"
).split()


def generate_password(length: int = 20, words: int = 0) -> str:
    import secrets

    if words and words > 0:
        words = max(3, min(int(words), 12))
        phrase = "-".join(secrets.choice(_WORDS) for _ in range(words))
        bits = words * (len(_WORDS).bit_length() - 1)
        return f"{phrase}\n(~{bits} bits of entropy from {len(_WORDS)} possible words)"
    length = max(8, min(int(length), 128))
    alphabet = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789!@#$%^&*-_=+"
    while True:
        pw = "".join(secrets.choice(alphabet) for _ in range(length))
        if any(c.islower() for c in pw) and any(c.isupper() for c in pw) and any(c.isdigit() for c in pw):
            return f"{pw}\n({length} characters, ~{int(length * 6.09)} bits of entropy)"


def tor_check(net: Net) -> str:
    body, _ = net.fetch("https://check.torproject.org/api/ip")
    data = json.loads(body)
    is_tor = str(data.get("IsTor")).lower() == "true"
    exit_ip = data.get("IP", "?")
    if is_tor:
        return f"Yes - traffic exits through Tor. Exit relay IP: {exit_ip}. You are anonymous."
    return f"No - traffic is NOT going through Tor. Your visible IP is {exit_ip} (not anonymous)."


# ---------------------------------------------------------------- knowledge / learning

def _split_sources(value) -> list:
    if isinstance(value, list):
        return [str(s) for s in value]
    if isinstance(value, str):
        return [s.strip() for s in re.split(r"[,\n]", value) if s.strip()]
    return []


def _save_knowledge(knowledge: Optional[Knowledge], args: dict) -> str:
    if knowledge is None:
        return "Knowledge storage is disabled."
    topic, notes = str(args.get("topic", "")).strip(), str(args.get("notes", "")).strip()
    if not topic or not notes:
        return "Error: both a topic and notes are required."
    knowledge.learn(topic, notes, _split_sources(args.get("sources")))
    return f"Learned and saved notes on '{topic}'."


def _recall_knowledge(knowledge: Optional[Knowledge], topic: str) -> str:
    if knowledge is None:
        return "Knowledge storage is disabled."
    entry = knowledge.get(topic)
    if not entry:
        return f"You have not studied '{topic}' yet."
    sources = "\n\nSources: " + ", ".join(entry["sources"]) if entry.get("sources") else ""
    return f"Your notes on {entry['topic']} (studied {entry.get('updated', '?')}):\n\n{entry['notes']}{sources}"


def _list_knowledge(knowledge: Optional[Knowledge]) -> str:
    if knowledge is None:
        return "Knowledge storage is disabled."
    topics = knowledge.topics()
    if not topics:
        return "You have not studied anything yet."
    return "Topics you have studied:\n" + "\n".join(f"- {t}" for t in topics)
