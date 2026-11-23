"""Build the website: one home page + one page per project, from templates/ and data/projects.json.

Run from the site folder after changing a template or the project list:
    python scripts/build.py

It writes index.html, one worldskills-<year>-test-project-<n>.html per project, 404.html, sitemap.xml and robots.txt.
Do not edit those generated files by hand; edit templates/*.html or data/projects.json and run this again.
(Needs only Python 3, no packages.)
"""
import base64
import datetime
import hashlib
import html
import json
import os
import re
import sys

SITE_URL = "https://machinisthands.github.io/worldskills/"  # where the site is published (ends with /)
SITE_NAME = "Machinist Hands"
BLOG_URL = "https://machinisthands.blogspot.com/"

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = sys.argv[1] if len(sys.argv) > 1 else ROOT  # optional: build into another folder
PREVIEW = "--preview" in sys.argv                 # used only for the claude.ai preview copy
IMG = "jpg" if "--jpg" in sys.argv else "webp"     # page images (card, drawing) are WebP; og.jpg is for social previews

esc = html.escape


def read(*parts):
    with open(os.path.join(ROOT, *parts), encoding="utf-8") as f:
        return f.read()


def fill(template, **values):
    for key, value in values.items():
        template = template.replace("{{" + key + "}}", str(value))
    return template


def page_name(p):
    return f"worldskills-{p['year']}-test-project-{p['project']}.html"


def asset(p, name):
    return f"projects/{p['dir']}/{name}"


def size(kb):
    return f"{kb / 1024:.1f} MB" if kb >= 1024 else f"{kb} KB"


def label(p):
    return f"{p['year']} · Test Project {p['project']}"


def notes_html(p):
    """Machining notes from notes/<dir>.md, as HTML ("" if the file is missing or empty).
    Supports: paragraphs, "## heading", "- item" lists, "1. item" numbered lists, **bold**.
    Lines starting with "<!--" are comments and are skipped."""
    path = os.path.join(ROOT, "notes", p["dir"] + ".md")
    if not os.path.exists(path):
        return ""
    out, para, lst = [], [], None

    def inline(text):
        return re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", esc(text))

    def flush():
        nonlocal para, lst
        if para:
            out.append("<p>" + inline(" ".join(para)) + "</p>")
            para = []
        if lst:
            out.append(f"<{lst[0]}>" + "".join(f"<li>{inline(i)}</li>" for i in lst[1]) + f"</{lst[0]}>")
            lst = None

    for line in open(path, encoding="utf-8").read().splitlines():
        t = line.strip()
        if t.startswith("<!--"):
            continue
        m_ul, m_ol = re.match(r"^[-*]\s+(.*)", t), re.match(r"^\d+[.)]\s+(.*)", t)
        if not t:
            flush()
        elif t.startswith("#"):
            flush()
            out.append("<h3>" + inline(t.lstrip("#").strip()) + "</h3>")
        elif m_ul or m_ol:
            kind = "ul" if m_ul else "ol"
            if para or (lst and lst[0] != kind):
                flush()
            lst = lst or [kind, []]
            lst[1].append((m_ul or m_ol).group(1))
        else:
            if lst:
                flush()
            para.append(t)
    flush()
    if not out:
        return ""
    return ('<section class="notes" aria-labelledby="h-notes">\n'
            '  <h2 id="h-notes" class="section-title">Machining Notes</h2>\n  ' + "\n  ".join(out) + "\n</section>")


def medals_html(year):
    """Gold/silver/bronze list for one year; empty if the year has no entry in data/medallists.json."""
    rows = medallists.get(str(year), [])
    return "".join(f'<li class="m-{m.lower()}"><b>{m}</b> {esc(name)} <span>{esc(country)}</span></li>'
                   for m, name, country in rows)


SHARE_ICON = ('<svg aria-hidden="true" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
              'stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="18" cy="5" r="3"/>'
              '<circle cx="6" cy="12" r="3"/><circle cx="18" cy="19" r="3"/><path d="M8.6 13.5l6.8 4M15.4 6.5l-6.8 4"/></svg>')


def share_html(url, title):
    """One Share button: the phone's own share menu, or "copy link" on computers (see js/app.js)."""
    return (f'<div class="share-row" data-url="{esc(url)}" data-title="{esc(title)}">'
            f'<button type="button" class="share-btn">{SHARE_ICON} Share</button></div>')


def behind_html(p):
    """"Behind this model": the A3 photocopy I modelled the part from (projects/<dir>/a3.webp), if there is one."""
    if "a3H" not in p:
        return ""
    pencil = (", and you can see a few of my pencil notes on it, where the drawing made me stop and check"
              if p.get("a3Pencil") else "")
    big, small = asset(p, "a3.webp"), asset(p, "a3-800.webp")
    return ('<section class="behind" aria-labelledby="h-behind">\n'
            '  <h2 id="h-behind" class="section-title">Behind this model</h2>\n'
            '  <p>I modelled this part in Siemens NX during the 2020–2021 lockdown, working from this A3 photocopy '
            f'of the drawing. I still have it{pencil}.</p>\n'
            f'  <figure class="a3"><a href="{big}"><img src="{small}" srcset="{small} 800w, {big} {p["a3W"]}w" '
            'sizes="(min-width: 760px) 700px, calc(100vw - 32px)" '
            f'alt="Photo of my A3 photocopy of the WorldSkills {p["year"]} Test Project {p["project"]} drawing, '
            f'with pencil and eraser" width="{p["a3W"]}" height="{p["a3H"]}" loading="lazy" decoding="async"></a>\n'
            '    <figcaption>The A3 copy I worked from · tap to enlarge</figcaption></figure>\n'
            '  <p><a href="index.html#story">Read the full story</a></p>\n</section>')


def jsonld(data):
    return json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")


def inline_css():
    """css/style.css, minified, for a <style> tag in every page: one less request that blocks the first paint.
    (GitHub Pages caches files for only 10 minutes, so a separate CSS file gains little from the browser cache.)"""
    css = read("css", "style.css").replace("url(../fonts/", "url(fonts/")
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    css = re.sub(r"\s+", " ", css)
    css = re.sub(r"\s*([{};,])\s*", r"\1", css)
    css = re.sub(r":\s+", ":", css).replace(";}", "}")
    return css.strip()


projects = json.loads(read("data", "projects.json"))
years = sorted({p["year"] for p in projects})
medallists = json.loads(read("data", "medallists.json"))
CSS = inline_css()
# Content Security Policy (GitHub Pages cannot send headers, so it goes in a <meta> tag).
# Google AdSense: Google publishes no list of ad domains (they change over time) and only supports a
# per-request nonce, which a static GitHub Pages site cannot make. So scripts, frames and connections
# are allowed from any https: address, with inline/eval as in Google's documented AdSense policy.
# Still blocked: plugins (object-src), <base> changes and form posts.
FIREBASE_AUTH_DOMAIN = "worldskills-like-dislike-share.firebaseapp.com"
CSP = "; ".join([
    "default-src 'self'",
    "script-src 'self' 'unsafe-inline' 'unsafe-eval' 'wasm-unsafe-eval' https:",
    "style-src 'self' 'unsafe-inline'",
    "img-src 'self' data: blob: https:",
    "font-src 'self'",
    "connect-src 'self' https:",
    "frame-src https:",
    "worker-src 'self' blob:",
    "manifest-src 'self'",
    "object-src 'none'",
    "base-uri 'self'",
    "form-action 'none'",
    "upgrade-insecure-requests",
])
layout = read("templates", "layout.html").replace("{{css}}", "<style>" + CSS + "</style>").replace("{{csp}}", CSP)
build_year = datetime.date.today().year
organization = {"@type": "Organization", "@id": BLOG_URL + "#org", "name": SITE_NAME, "url": BLOG_URL,
                "logo": SITE_URL + "icon-512.png"}
website = {"@type": "WebSite", "@id": SITE_URL + "#website", "url": SITE_URL,
           "name": "WorldSkills CNC Milling Test Projects", "publisher": {"@id": organization["@id"]}}
# Card width on the home page (grid: 1120px max, 16px gaps, columns of at least 320px).
CARD_SIZES = ("(min-width: 1152px) 363px, (min-width: 1024px) calc((100vw - 64px) / 3), "
              "(min-width: 688px) calc((100vw - 48px) / 2), calc(100vw - 32px)")


def card_srcset(p):
    """Small screens or 1x screens get the 400px card, sharper screens the 800px one (WebP only)."""
    return f'{asset(p, "card-400.webp")} 400w, {asset(p, "card.webp")} 800w' if IMG == "webp" else ""


scripts_common = '<script src="js/app.js" defer></script>'


def write(name, text):
    with open(os.path.join(OUT, name), "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


# ---------- Home page ----------
year_blocks = []
for y in years:
    items = [p for p in projects if p["year"] == y]
    cards = []
    for p in items:
        first = p is projects[0]
        loading = 'fetchpriority="high"' if first else ('loading="eager"' if projects.index(p) < 3 else 'loading="lazy"')
        cards.append(
            f'<li><a class="card" href="{page_name(p)}">'
            f'<img src="{asset(p, "card." + IMG)}"'
            + (f' srcset="{card_srcset(p)}" sizes="{CARD_SIZES}"' if card_srcset(p) else "")
            + f' alt="3D model of WorldSkills {label(p)}: top side (left) and bottom side (right)" '
            f'width="800" height="400" {loading} decoding="async">'
            f'<div class="card-body"><h3>Test Project {p["project"]}</h3>'
            f'<span class="card-views" data-page="{page_name(p)[:-5]}" hidden><b></b></span>'
            f'<span class="card-cta">View 3D →</span></div></a></li>')
    year_blocks.append(
        f'<section class="year-block" aria-labelledby="y{y}">\n'
        f'  <h2 id="y{y}" class="year-head">{y} <span>{esc(items[0]["host"])} · {len(items)} projects</span></h2>\n'
        f'  <ul class="grid">\n    ' + "\n    ".join(cards) + '\n  </ul>\n</section>')

home_title = "WorldSkills CNC Milling Test Projects in 3D | Machinist Hands"
home_desc = (f"All WorldSkills CNC Milling test projects {years[0]}–{years[-1]}: rotate each part in 3D, "
             "study the drawings and download the PDF and 3D model.")
home_ld = {"@context": "https://schema.org", "@graph": [organization, website, {
    "@type": "CollectionPage", "@id": SITE_URL, "url": SITE_URL, "name": home_title, "description": home_desc,
    "isPartOf": {"@id": website["@id"]}, "inLanguage": "en",
    "primaryImageOfPage": SITE_URL + asset(projects[0], "og.jpg"),
    "mainEntity": {"@type": "ItemList", "numberOfItems": len(projects), "itemListElement": [
        {"@type": "ListItem", "position": i + 1, "url": SITE_URL + page_name(p),
         "name": f"WorldSkills {label(p)}"} for i, p in enumerate(projects)]}}]}

write("index.html", fill(
    layout, title=esc(home_title), description=esc(home_desc), url=SITE_URL, og_type="website",
    image=SITE_URL + asset(projects[0], "og.jpg"), image_alt="3D models of WorldSkills CNC Milling test projects",
    preload=(f'<link rel="preload" href="{asset(projects[0], "card." + IMG)}" as="image" fetchpriority="high"'
             + (f' imagesrcset="{card_srcset(projects[0])}" imagesizes="{CARD_SIZES}"' if card_srcset(projects[0]) else "")
             + '>\n'),
    jsonld=jsonld(home_ld), build_year=build_year, base="", robots="index, follow, max-image-preview:large",
    scripts=scripts_common,
    content=fill(read("templates", "home.html"), first_year=years[0], last_year=years[-1],
                 years="\n".join(year_blocks),
                 share=share_html(SITE_URL, f"WorldSkills CNC Milling test projects {years[0]}–{years[-1]} in 3D"))))

# ---------- Project pages ----------
project_tpl = read("templates", "project.html")
for i, p in enumerate(projects):
    same_year = [q for q in projects if q["year"] == p["year"]]
    year_options = "".join(
        f'<option value="{page_name(next(q for q in projects if q["year"] == y))}"{" selected" if y == p["year"] else ""}>{y}</option>'
        for y in years)
    project_options = "".join(
        f'<option value="{page_name(q)}"{" selected" if q is p else ""}>Test Project {q["project"]}</option>' for q in same_year)
    pager = []
    for q, d in ((projects[i - 1] if i > 0 else None, "prev"), (projects[i + 1] if i + 1 < len(projects) else None, "next")):
        if not q:
            continue
        word = "Previous" if d == "prev" else "Next"
        pager.append(
            f'<a class="pager-link {d}" href="{page_name(q)}" rel="{d}">'
            f'<span class="pager-arrow" aria-hidden="true">{"←" if d == "prev" else "→"}</span>'
            f'<img src="{asset(q, "top.jpg")}" alt="" width="48" height="48" loading="lazy" decoding="async">'
            f'<span class="pager-text"><small>{word}</small><b>{q["year"]} · TP {q["project"]}</b></span></a>')

    file = f"WorldSkills-{p['year']}-CNC-Milling-TP{p['project']}"
    url = SITE_URL + page_name(p)
    title = f"WorldSkills {p['year']} CNC Milling Test Project {p['project']} | Machinist Hands"
    desc = (f"WorldSkills {p['year']} ({p['host']}) CNC Milling Test Project {p['project']}: view the part in 3D, "
            f"study the engineering drawing and download the PDF and 3D model.")
    ld = {"@context": "https://schema.org", "@graph": [organization, website,
        {"@type": "WebPage", "@id": url, "url": url, "name": title, "description": desc, "inLanguage": "en",
         "isPartOf": {"@id": website["@id"]}, "breadcrumb": {"@id": url + "#breadcrumb"},
         "primaryImageOfPage": SITE_URL + asset(p, "og.jpg"), "mainEntity": {"@id": url + "#project"}},
        {"@type": "BreadcrumbList", "@id": url + "#breadcrumb", "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": "WorldSkills CNC Milling Test Projects", "item": SITE_URL},
            {"@type": "ListItem", "position": 2, "name": label(p), "item": url}]},
        {"@type": "LearningResource", "@id": url + "#project",
         "name": f"WorldSkills {p['year']} CNC Milling Test Project {p['project']}",
         "description": desc, "learningResourceType": "Test project", "educationalLevel": "Competition",
         "about": ["CNC milling", "Machining", "Engineering drawing"], "inLanguage": "en",
         "image": [SITE_URL + asset(p, "og.jpg"), SITE_URL + asset(p, "drawing.webp")]
                  + ([SITE_URL + asset(p, "a3.webp")] if "a3H" in p else []),
         "copyrightHolder": {"@type": "Organization", "name": "WorldSkills International"},
         "contentLocation": {"@type": "Place", "name": p["host"]}, "temporalCoverage": str(p["year"]),
         "publisher": {"@id": organization["@id"]},
         "hasPart": [
             {"@type": "3DModel", "name": f"{label(p)} 3D model", "contentUrl": SITE_URL + asset(p, "model.glb"),
              "encodingFormat": "model/gltf-binary", "contentSize": f"{p['glbKB']} KB",
              "creator": {"@id": organization["@id"]}},
             {"@type": "DigitalDocument", "name": f"{label(p)} engineering drawing (PDF)",
              "url": SITE_URL + asset(p, "drawing.pdf"), "encodingFormat": "application/pdf"}]}]}

    model = asset(p, "model.js" if PREVIEW else "model.glb")
    scripts = (scripts_common + '\n<script src="js/vendor/three-bundle.min.js" defer></script>\n'
               '<script src="js/viewer.js" defer></script>\n<script src="js/comments.js" defer></script>')
    write(page_name(p), fill(
        layout, title=esc(title), description=esc(desc), url=url, og_type="article",
        image=SITE_URL + asset(p, "og.jpg"), image_alt=f"3D model of WorldSkills {label(p)}, top and bottom",
        preload="", jsonld=jsonld(ld), build_year=build_year, scripts=scripts, base="",
        robots="index, follow, max-image-preview:large",
        content=fill(project_tpl, year=p["year"], project=p["project"], host=esc(p["host"]),
                     year_options=year_options, project_options=project_options, model=model,
                     drawing=asset(p, "drawing." + IMG), drawing_w=p["drawingW"], drawing_h=p["drawingH"],
                     pdf=asset(p, "drawing.pdf"), glb=asset(p, "model.glb"), file=file,
                     pdf_size=size(p["pdfKB"]), glb_size=size(p["glbKB"]), pager="\n".join(pager),
                     notes=notes_html(p), medals=medals_html(p["year"]), behind=behind_html(p),
                     page_id=page_name(p)[:-5],
                     share=share_html(url, f"WorldSkills {p['year']} CNC Milling Test Project {p['project']} in 3D"))))

# ---------- 404 page (GitHub Pages shows 404.html for any missing address) ----------
# <base> makes its links and files work whatever address the visitor mistyped.
if not PREVIEW:
    nf_desc = "This page does not exist. See all WorldSkills CNC Milling test projects."
    write("404.html", fill(
        layout, title="Page not found | Machinist Hands", description=nf_desc, url=SITE_URL, og_type="website",
        image=SITE_URL + asset(projects[0], "og.jpg"), image_alt="WorldSkills CNC Milling test projects",
        base=f'<base href="{SITE_URL}">\n', preload="", robots="noindex", build_year=build_year,
        jsonld=jsonld({"@context": "https://schema.org", "@graph": [organization, website]}), scripts=scripts_common,
        content='<section class="hero not-found" aria-labelledby="page-title">\n'
                '  <p class="eyebrow">Error 404</p>\n  <h1 id="page-title">Page not found</h1>\n'
                '  <p class="lead">The page you were looking for does not exist or has moved.</p>\n'
                '  <p class="lead"><a href="index.html">See all WorldSkills CNC Milling test projects →</a></p>\n</section>'))

# ---------- sitemap.xml and robots.txt ----------
today = datetime.date.today().isoformat()
urls = [SITE_URL] + [SITE_URL + page_name(p) for p in projects]
write("sitemap.xml", '<?xml version="1.0" encoding="UTF-8"?>\n'
      '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
      + "".join(f"  <url><loc>{u}</loc><lastmod>{today}</lastmod></url>\n" for u in urls) + "</urlset>\n")
write("robots.txt", f"User-agent: *\nAllow: /\n\nSitemap: {SITE_URL}sitemap.xml\n")
print(f"Built index.html + {len(projects)} project pages, 404.html, sitemap.xml, robots.txt in {OUT}")
