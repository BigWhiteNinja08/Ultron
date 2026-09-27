import json

import pytest

from ultron import tools
from ultron.memory import Memory
from ultron.tools import ToolError, calculate, html_to_text, parse_duckduckgo, run_tool


@pytest.mark.parametrize(
    "expression,result",
    [
        ("17*23", "391"),
        ("2^10", "1024"),
        ("sqrt(2)*sqrt(2)", "2.0000000000000004"),
        ("factorial(20)", "2432902008176640000"),
        ("(3+4)*2 - 10/4", "11.5"),
        ("round(pi, 5)", "3.14159"),
        ("gcd(84, 36)", "12"),
    ],
)
def test_calculator(expression, result):
    assert calculate(expression).endswith("= " + result)


@pytest.mark.parametrize(
    "expression",
    ["__import__('os').system('ls')", "open('x')", "9**9**9", "(10**1000)**10000", "factorial(5000)", "a+1", "1/0"],
)
def test_calculator_rejects_unsafe_or_huge(expression):
    with pytest.raises(ToolError):
        calculate(expression)


def test_calculator_describes_huge_integers():
    assert "digits" in calculate("7**9999")


def test_run_tool_reports_errors_as_text(memory):
    assert run_tool("calculate", {"expression": "1/0"}).startswith("Error:")
    assert run_tool("self_destruct", {}).startswith("Error: unknown tool")
    assert run_tool("open_url", {"url": "file:///etc/passwd"}).startswith("Error: only http(s)")


@pytest.mark.parametrize("url", ["http://127.0.0.1:11434/api/tags", "http://localhost/", "http://192.168.1.1/admin"])
def test_open_url_blocks_local_network(url):
    assert "off limits" in run_tool("open_url", {"url": url})


def test_remember(memory):
    assert run_tool("remember", {"fact": "Ime mu je Luka."}, memory) == "Stored."
    assert run_tool("remember", {"fact": "ime mu je   luka."}, memory).startswith("Already known")
    assert Memory(memory.path).facts == ["Ime mu je Luka."]
    assert run_tool("remember", {"fact": "x"}, None) == "Memory is disabled."


DDG_SAMPLE = """
<div class="result results_links results_links_deep web-result">
  <h2 class="result__title">
    <a rel="nofollow" class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fen.wikipedia.org%2Fwiki%2FUltron&amp;rut=abc">Ultron - <b>Wikipedia</b></a>
  </h2>
  <a class="result__snippet" href="//duckduckgo.com/l/?uddg=x">Ultron is a supervillain appearing in <b>Marvel</b> Comics.</a>
</div>
<div class="result results_links results_links_deep web-result">
  <h2 class="result__title">
    <a rel="nofollow" class="result__a" href="https://www.marvel.com/characters/ultron">Ultron | Marvel</a>
  </h2>
  <a class="result__snippet" href="https://www.marvel.com/characters/ultron">Robot &amp; villain.</a>
</div>
"""


def test_parse_duckduckgo():
    results = parse_duckduckgo(DDG_SAMPLE)
    assert results == [
        {
            "title": "Ultron - Wikipedia",
            "url": "https://en.wikipedia.org/wiki/Ultron",
            "snippet": "Ultron is a supervillain appearing in Marvel Comics.",
        },
        {"title": "Ultron | Marvel", "url": "https://www.marvel.com/characters/ultron", "snippet": "Robot & villain."},
    ]


class FakeNet:
    def __init__(self, fetch, tor=False):
        self.fetch = fetch
        self.tor = tor


def test_web_search_falls_back_to_wikipedia():
    def fake_fetch(url, agent=None, data=None):
        if "duckduckgo" in url:
            raise ToolError("HTTP 202")
        return json.dumps({"query": {"search": [{"title": "Ultron", "snippet": "a <b>robot</b>"}]}}), "application/json"

    out = tools.web_search("ultron", FakeNet(fake_fetch))
    assert "(via wikipedia (web search unavailable))" in out
    assert "https://en.wikipedia.org/wiki/Ultron" in out
    assert "a robot" in out


def test_web_search_uses_duckduckgo():
    out = tools.web_search("ultron", FakeNet(lambda url, agent=None, data=None: (DDG_SAMPLE, "text/html")))
    assert out.startswith("Search results for 'ultron' (via web):")
    assert "https://www.marvel.com/characters/ultron" in out


def test_web_search_reports_tor_route():
    out = tools.web_search("ultron", FakeNet(lambda url, agent=None, data=None: (DDG_SAMPLE, "text/html"), tor=True))
    assert out.startswith("Search results for 'ultron' (via Tor):")


def test_html_to_text():
    title, text = html_to_text(
        "<html><head><title>Sokovia</title><style>p{}</style></head>"
        "<body><nav>menu</nav><h1>Sokovia</h1><p>A small   country.</p><script>x()</script></body></html>"
    )
    assert title == "Sokovia"
    assert text == "Sokovia\nA small country."


@pytest.mark.parametrize(
    "text,found",
    [
        ("Koliko je 12345 * 6789?", ["12345 * 6789 = 83810205"]),
        ("kaj je 2^64", ["2**64 = 18446744073709551616"]),
        ("(3+4)*200 prosim", ["(3+4)*200 = 1400"]),
        ("12 x 350", ["12 * 350 = 4200"]),
        ("kaj je 3+4", []),
        ("rojen 1990-05-12", []),
        ("leta 1990-2000", []),
        ("tel 041-123-456", []),
        ("daj mi 1-2 ideji", []),
    ],
)
def test_find_arithmetic(text, found):
    assert tools.find_arithmetic(text) == found


@pytest.mark.parametrize(
    "text,query",
    [
        ("Kdo je režiral film Avengers: Age of Ultron? Poišči na internetu.", "Kdo je režiral film Avengers: Age of Ultron?"),
        ("poišči mi na internetu vreme v Ljubljani", "vreme v Ljubljani"),
        ("Search the web for latest Python version", "latest Python version"),
        ("guglaj ceno bitcoina", "ceno bitcoina"),
        ("Poišči napako v moji kodi", None),
        ("Preveri mojo kodo", None),
        ("Poišči na internetu.", None),
        ("Kaj je smisel življenja?", None),
    ],
)
def test_search_request(text, query):
    assert tools.search_request(text) == query
