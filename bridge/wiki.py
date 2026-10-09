"""Local searchable copy of unboundwiki.com's pokemon/, items/ and locations/ sections (#28).

python wiki.py crawl                 fetch every sitemap page into wiki/pages/ (resumable, 1 req/s)
python wiki.py index                 build wiki/index.sqlite (FTS5) from the cached pages
python wiki.py search "query" [N]    top N hits: url, title, snippet
python wiki.py read URL_OR_SLUG      print a page's text
"""
import json
import re
import sqlite3
import sys
import time
import urllib.request
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent / "wiki"
PAGES = ROOT / "pages"
DB = ROOT / "index.sqlite"
SITE = "https://unboundwiki.com/"
UA = "ClaudeUnbound-wiki-indexer/1.0 (personal research harness)"
DELAY = 1.0
# Reference data only. Walkthrough, missions, gyms etc. are deliberately excluded: the agent works out the story itself.
ALLOWED_SECTIONS = {"pokemon", "items", "locations"}

BLOCK = {"p", "div", "h1", "h2", "h3", "h4", "h5", "h6", "li", "ul", "ol", "table", "br", "section", "blockquote", "dl", "dt", "dd"}
SKIP = {"script", "style", "noscript", "form", "svg", "button"}
VOID = {"br", "img", "hr", "input", "meta", "link", "source", "wbr", "col"}


class Extract(HTMLParser):
    """Text of <h1> plus everything inside div.text-content; tables become `|` rows."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.depth = 0      # div depth inside text-content; 0 = outside
        self.skip = 0
        self.out, self.row, self.cell = [], None, None
        self.title, self.in_h1 = "", False

    def handle_starttag(self, tag, attrs):
        if tag in VOID:
            if self.depth and tag == "br":
                self.write("\n")
            return
        if tag == "h1" and not self.title:
            self.in_h1 = True
        if not self.depth:
            if tag == "div" and "text-content" in (dict(attrs).get("class") or "").split():
                self.depth = 1
            return
        if tag == "div":
            self.depth += 1
        if tag in SKIP:
            self.skip += 1
        elif tag == "tr":
            self.row = []
        elif tag in ("td", "th"):
            self.cell = []
        elif tag in BLOCK:
            self.write("\n")
        if tag.startswith("h") and tag[1:].isdigit():
            self.write("#" * int(tag[1:]) + " ")
        elif tag == "li":
            self.write("- ")

    def handle_endtag(self, tag):
        if tag == "h1":
            self.in_h1 = False
        if not self.depth or tag in VOID:
            return
        if tag in SKIP:
            self.skip = max(0, self.skip - 1)
        elif tag in ("td", "th") and self.cell is not None and self.row is not None:
            self.row.append(" ".join("".join(self.cell).split()))
            self.cell = None
        elif tag == "tr" and self.row is not None:
            if any(self.row):
                self.out.append("\n| " + " | ".join(self.row) + " |")
            self.row = None
        elif tag in BLOCK:
            self.write("\n")
        if tag == "div":
            self.depth -= 1

    def handle_data(self, data):
        if self.in_h1:
            self.title += data
        if self.depth and not self.skip:
            self.write(data)

    def write(self, s):
        (self.cell if self.cell is not None else self.out).append(s)

    def text(self):
        lines = [" ".join(l.split()) for l in "".join(self.out).split("\n")]
        text = re.sub(r"\n{3,}", "\n\n", "\n".join(lines))
        return re.sub(r"\|\n\n(?=\|)", "|\n", text).strip()


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", "replace")


def slug(url):
    path = url.replace(SITE, "").strip("/")
    return path.replace("/", "__") or "index"


def section(url):
    return url.replace(SITE, "").split("/")[0]


def extract(url, html):
    p = Extract()
    p.feed(html)
    title = " ".join(p.title.split()) or re.sub(r"\s*-\s*Pokémon Unbound Wiki$", "", re.search(r"<title>(.*?)</title>", html, re.S).group(1)).strip()
    return {"url": url, "title": title, "section": section(url), "text": p.text()}


def sitemap_urls():
    locs = lambda xml: re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", xml)
    urls = []
    for sm in locs(get(SITE + "sitemap_index.xml")):
        time.sleep(DELAY)
        urls += locs(get(sm))
    return [u for u in dict.fromkeys(urls) if section(u) in ALLOWED_SECTIONS]


def crawl():
    PAGES.mkdir(parents=True, exist_ok=True)
    urls = sitemap_urls()
    todo = [u for u in urls if not (PAGES / f"{slug(u)}.json").exists()]
    print(f"{len(urls)} urls, {len(urls) - len(todo)} cached, {len(todo)} to fetch", flush=True)
    failed = []
    for i, url in enumerate(todo, 1):
        time.sleep(DELAY)
        try:
            page = extract(url, get(url))
        except Exception as e:  # keep going; a rerun retries anything not cached
            failed.append(url)
            print(f"[{i}/{len(todo)}] FAIL {url}: {e}", flush=True)
            continue
        (PAGES / f"{slug(url)}.json").write_text(json.dumps(page, ensure_ascii=False), encoding="utf-8")
        print(f"[{i}/{len(todo)}] {url} ({len(page['text'])} chars)", flush=True)
    print(f"done: {len(todo) - len(failed)} fetched, {len(failed)} failed", flush=True)
    for u in failed:
        print("failed:", u)


EXCLUDED_HEADINGS = ("missions",)  # user decision: no mission content, even on allowed pages


def strip_excluded(text):
    """Drop '## Missions'-style sections (heading through the next '## ' heading)."""
    out, skip = [], False
    for line in text.splitlines():
        if line.startswith("## "):
            skip = line[3:].strip().lower().startswith(EXCLUDED_HEADINGS)
        if not skip:
            out.append(line)
    return "\n".join(out)


def index():
    DB.unlink(missing_ok=True)
    db = sqlite3.connect(DB)
    db.execute("CREATE VIRTUAL TABLE pages USING fts5(title, section UNINDEXED, url UNINDEXED, text, tokenize='unicode61 remove_diacritics 2')")
    rows = [json.loads(f.read_text(encoding="utf-8")) for f in PAGES.glob("*.json")]
    rows = [{**r, "text": strip_excluded(r["text"])} for r in rows if r["section"] in ALLOWED_SECTIONS]
    db.executemany("INSERT INTO pages VALUES (:title, :section, :url, :text)", rows)
    db.commit()
    print(f"indexed {len(rows)} pages into {DB}")


def search(query, n=5):
    """Top n pages for a free-text query: [{url, title, section, snippet}]. Title matches weigh 10x."""
    terms = re.findall(r"\w+", query)
    if not terms:
        return []
    # Pages containing every term first, then any term; each tier ranked by bm25.
    # ponytail: no phrase/prefix syntax; add if queries need it
    quoted = [f'"{t}"' for t in terms]
    db = sqlite3.connect(DB)
    hits = {}
    for fts in (" AND ".join(quoted), " OR ".join(quoted)):
        for r in db.execute(
                "SELECT url, title, section, snippet(pages, 3, '[', ']', ' ... ', 40) FROM pages "
                "WHERE pages MATCH ? ORDER BY bm25(pages, 10.0, 0, 0, 1.0) LIMIT ?", (fts, n)):
            hits.setdefault(r[0], dict(zip(("url", "title", "section", "snippet"), r)))
    return list(hits.values())[:n]


def read(url_or_slug):
    """Full cached page {url, title, section, text} for a wiki URL, a path like 'pokemon/snorunt', or a slug."""
    # Any form of the site's own address works: full URL, without the scheme ('unboundwiki.com/locations/x'), a path, a slug.
    path = re.sub(r"^(?:https?://)?(?:www\.)?unboundwiki\.com/", "", url_or_slug.strip())
    s = path if path.startswith("http") else SITE + path.replace("__", "/").strip("/") + "/"
    if section(s) not in ALLOWED_SECTIONS:
        raise KeyError(f"{url_or_slug!r} is outside the indexed sections {sorted(ALLOWED_SECTIONS)}")
    f = PAGES / f"{slug(s)}.json"
    if not f.exists():
        raise KeyError(f"no cached page for {url_or_slug!r}: don't guess addresses, find the page with wiki_search")
    page = json.loads(f.read_text(encoding="utf-8"))
    return {**page, "text": strip_excluded(page["text"])}


def _selftest():
    assert strip_excluded("## Trainers\nA\n## Missions\nsecret\n### Sub\nmore\n## Vendors\nB") == \
        "## Trainers\nA\n## Vendors\nB"
    html = ('<nav>menu</nav><h1>Snorunt</h1><div class="text-content"><h2>Abilities</h2><p>Inner&nbsp;Focus</p>'
            '<div class="table-wrap"><table><tr><th>Lv</th><th>Move</th></tr><tr><td>1</td><td>Powder <b>Snow</b></td></tr></table></div>'
            '<script>x()</script></div><footer>foot</footer>')
    p = extract(SITE + "pokemon/snorunt/", html)
    assert p["title"] == "Snorunt" and p["section"] == "pokemon", p
    assert p["text"] == "## Abilities\n\nInner Focus\n\n| Lv | Move |\n| 1 | Powder Snow |", repr(p["text"])
    assert slug(SITE + "pokemon/snorunt/") == "pokemon__snorunt"
    try:
        read("walkthrough/part-1")
        raise AssertionError("read() must refuse sections outside ALLOWED_SECTIONS")
    except KeyError:
        pass


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    _selftest()
    cmd, args = (sys.argv[1] if len(sys.argv) > 1 else ""), sys.argv[2:]
    if cmd == "crawl":
        crawl()
    elif cmd == "index":
        index()
    elif cmd == "search" and args:
        for h in search(args[0], int(args[1]) if len(args) > 1 else 5):
            print(f"{h['url']}\n  {h['title']} [{h['section']}]\n  {h['snippet']}\n")
    elif cmd == "read" and args:
        p = read(args[0])
        print(f"{p['title']}\n{p['url']}\n\n{p['text']}")
    else:
        print(__doc__)
