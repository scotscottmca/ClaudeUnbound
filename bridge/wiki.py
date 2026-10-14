"""Local searchable copy of unboundwiki.com's pokemon/, items/ and locations/ sections (#28).

python wiki.py crawl                 fetch every sitemap page into wiki/pages/ (resumable, 1 req/s)
python wiki.py index                 build wiki/index.sqlite (FTS5) from the cached pages
python wiki.py search "query" [N]    top N hits: url, title, snippet
python wiki.py read URL_OR_SLUG      print a page's text
python wiki.py crawl-lastresort      fetch walkthrough/ and gyms/ into wiki/lastresort_pages/ (kept apart)
python wiki.py index-lastresort      build wiki/lastresort.sqlite and the per-section index lastresort_sections.json

The last-resort corpus (walkthrough, gyms) is separate on purpose: wiki_search/wiki_read never see it. The agent gets
it only through the harness-gated wiki_walkthrough tool, when really stuck (user, 2026-10-09), and nothing from it
may be written to memory (watcher.guard deletes lines copied from it).
"""
import json
import math
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
LAST_RESORT_SECTIONS = {"walkthrough", "gyms"}
LR_PAGES = ROOT / "lastresort_pages"
LR_DB = ROOT / "lastresort.sqlite"

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


def sitemap_urls(sections=ALLOWED_SECTIONS):
    locs = lambda xml: re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", xml)
    urls = []
    for sm in locs(get(SITE + "sitemap_index.xml")):
        time.sleep(DELAY)
        urls += locs(get(sm))
    return [u for u in dict.fromkeys(urls) if section(u) in sections]


def crawl(sections=ALLOWED_SECTIONS, pages=PAGES):
    pages.mkdir(parents=True, exist_ok=True)
    urls = sitemap_urls(sections)
    todo = [u for u in urls if not (pages / f"{slug(u)}.json").exists()]
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
        (pages / f"{slug(url)}.json").write_text(json.dumps(page, ensure_ascii=False), encoding="utf-8")
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


def index(sections=ALLOWED_SECTIONS, pages=PAGES, dbfile=DB):
    dbfile.unlink(missing_ok=True)
    db = sqlite3.connect(dbfile)
    db.execute("CREATE VIRTUAL TABLE pages USING fts5(title, section UNINDEXED, url UNINDEXED, text, tokenize='unicode61 remove_diacritics 2')")
    rows = [json.loads(f.read_text(encoding="utf-8")) for f in pages.glob("*.json")]
    rows = [{**r, "text": strip_excluded(r["text"])} for r in rows if r["section"] in sections]
    db.executemany("INSERT INTO pages VALUES (:title, :section, :url, :text)", rows)
    db.commit()
    print(f"indexed {len(rows)} pages into {dbfile}")


def search(query, n=5, dbfile=DB):
    """Top n pages for a free-text query: [{url, title, section, snippet}]. Title matches weigh 10x."""
    terms = re.findall(r"\w+", query)
    if not terms:
        return []
    # Pages containing every term first, then any term; each tier ranked by bm25.
    # ponytail: no phrase/prefix syntax; add if queries need it
    quoted = [f'"{t}"' for t in terms]
    db = sqlite3.connect(dbfile)
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


LR_DIGEST = ROOT / "lastresort_sections.json"
KEY_HEADINGS = ("step-by-step", "puzzle", "optimal", "path", "how to", "solution")


def digest():
    """Index the last-resort pages by section (#160): each heading's text with the in-game place names (map
    sections) it mentions, so the gated tool can serve the sections about where the player is, without a query."""
    names = json.load(open(Path(__file__).with_name("names.json"), encoding="utf-8"))["mapsecs"].values()
    places = sorted({v for v in names if len(v) > 3}, key=len, reverse=True)
    pages = sorted(LR_PAGES.glob("*.json"))
    out = []
    for f in pages:
        page = json.loads(f.read_text(encoding="utf-8"))
        path, buf = [], []

        def flush():
            text = "\n".join(buf).strip()
            if not text:
                return
            head = " > ".join(path) or page["title"]
            low_head, low, title = head.lower(), text.lower(), page["title"].lower()
            out.append({"page": page["title"], "url": page["url"], "heading": head, "text": text,
                        "places": [pl for pl in places if pl.lower() in low_head or pl.lower() in low],
                        "head_places": [pl for pl in places if pl.lower() in low_head or pl.lower() in title],
                        "key": any(k in low_head for k in KEY_HEADINGS)})

        for line in strip_excluded(page["text"]).splitlines():
            m = re.match(r"(#{1,6}) (.*)", line)
            if m:
                flush()
                depth = len(m.group(1))
                path = path[:max(0, depth - 2)] + [m.group(2).strip()]  # "## X" starts a path, "### Y" nests under it
                buf = []
                continue
            buf.append(line)
        flush()
    LR_DIGEST.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    print(f"{len(out)} sections from {len(pages)} pages into {LR_DIGEST}")


def sections_for(place=None, query="", n=4, budget=8000):
    """The most relevant walkthrough sections for PLACE (a map section name) and/or QUERY: sections whose heading or
    page title names the place first, puzzle/step-by-step headings first among them, then query-term hits."""
    secs = [s for s in json.loads(LR_DIGEST.read_text(encoding="utf-8")) if len(s["text"]) >= 300]  # not TOC scraps
    terms = [t.lower() for t in re.findall(r"\w+", query) if len(t) > 2]
    core = re.sub(r"\s+(City|Town|Village|Island|Isle)$", "", place or "").lower()  # "Fallshore Gym" is about Fallshore City
    # A term's weight is its rarity: "gym"/"puzzle" are in every gym section, so raw counts let a long Dehara gym
    # section outrank "Fallshore gym puzzle" (#159). Counts are capped; a term in the heading or page title counts most.
    idf = {t: math.log(len(secs) / (1 + sum(t in (s["heading"] + s["page"] + s["text"]).lower() for s in secs)))
           for t in terms}

    def score(s):
        named = core and (core in s["heading"].lower() or core in s["page"].lower())
        here = place and (place in s["places"] or named)
        head = (s["heading"] + " " + s["page"]).lower()
        return ((50 if named or (place and place in s["head_places"]) else 10 if here else 0)
                + (40 if s["key"] and (here or not place) else 0)
                + sum(max(idf[t], 0.1) * (min(s["text"].lower().count(t), 3) + 5 * (t in head)) for t in terms))

    out, used = [], 0
    for s in sorted((s for s in secs if score(s) > 0), key=score, reverse=True)[:n]:
        chunk = f"[{s['page']} > {s['heading']}]\n{s['text']}"[:budget - used]
        if chunk:
            out.append(chunk)
            used += len(chunk)
    return out


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
    elif cmd == "crawl-lastresort":
        crawl(LAST_RESORT_SECTIONS, LR_PAGES)
    elif cmd == "index-lastresort":
        index(LAST_RESORT_SECTIONS, LR_PAGES, LR_DB)
        digest()
    elif cmd == "search" and args:
        for h in search(args[0], int(args[1]) if len(args) > 1 else 5):
            print(f"{h['url']}\n  {h['title']} [{h['section']}]\n  {h['snippet']}\n")
    elif cmd == "read" and args:
        p = read(args[0])
        print(f"{p['title']}\n{p['url']}\n\n{p['text']}")
    else:
        print(__doc__)
