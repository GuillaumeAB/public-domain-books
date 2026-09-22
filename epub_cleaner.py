import os
import re
import uuid
from typing import Optional, Dict, Any
from bs4 import BeautifulSoup
import ebooklib
from ebooklib import epub
from downloader import clean_author_name

CLEAN_CSS = """
@charset "utf-8";

/* ==========================================================================
   Feuille de style élégante pour livre du domaine public
   Compatible Liseuses (Kindle, Kobo, Apple Books, Calibre, Thorium)
   ========================================================================== */

body {
    margin: 5% 5% 5% 5%;
    padding: 0;
    font-family: "Georgia", "Palatino Linotype", "Book Antiqua", "Garamond", "Times New Roman", serif;
    font-size: 1.05em;
    line-height: 1.65;
    text-align: justify;
    color: inherit;
    background: transparent;
    hyphens: auto;
    -webkit-hyphens: auto;
    -moz-hyphens: auto;
}

p {
    margin: 0;
    padding: 0;
    text-indent: 1.5em;
}

/* Pas d'alinéa pour le premier paragraphe suivant un titre ou séparateur */
h1 + p, h2 + p, h3 + p, h4 + p, hr + p, .no-indent, .first-p {
    text-indent: 0;
}

/* Titres */
h1, h2, h3, h4 {
    font-family: "Georgia", "Palatino", serif;
    font-weight: bold;
    text-align: center;
    text-indent: 0;
    line-height: 1.3;
    page-break-after: avoid;
    break-after: avoid;
}

h1 {
    font-size: 1.8em;
    margin-top: 2em;
    margin-bottom: 1em;
    letter-spacing: 0.05em;
    text-transform: uppercase;
}

h2 {
    font-size: 1.4em;
    margin-top: 1.8em;
    margin-bottom: 0.8em;
}

h3 {
    font-size: 1.15em;
    font-style: italic;
    margin-top: 1.4em;
    margin-bottom: 0.6em;
}

/* Citations et épigraphes */
blockquote {
    margin: 1.5em 2em;
    padding-left: 1em;
    border-left: 2px solid #aaa;
    font-style: italic;
    text-indent: 0;
}

/* Poésie / Vers */
.verse, pre {
    font-family: inherit;
    font-size: 0.95em;
    line-height: 1.5;
    text-align: left;
    text-indent: 0;
    margin: 1.2em 0 1.2em 2em;
    white-space: pre-wrap;
}

/* Séparateurs ornés */
hr {
    border: none;
    text-align: center;
    margin: 2em 0;
}

hr::before {
    content: "*  *  *";
    letter-spacing: 0.5em;
    color: #666;
    font-size: 0.9em;
}

/* Images */
img {
    max-width: 100%;
    height: auto;
    display: block;
    margin: 1.5em auto;
}

/* Notes de bas de page */
.footnote {
    font-size: 0.85em;
    line-height: 1.4;
    text-indent: 0;
    margin-top: 1em;
    border-top: 1px solid #ccc;
    padding-top: 0.5em;
}
"""

GUTENBERG_DISCLAIMER_PATTERNS = [
    r"\*\*\* START OF TH(IS|E) PROJECT GUTENBERG.*?(\*\*\*|$)",
    r"\*\*\* END OF TH(IS|E) PROJECT GUTENBERG.*?(\*\*\*|$)",
    r"This eBook is for the use of anyone anywhere.*?(Project Gutenberg|cost and with)",
    r"THIS EBOOK WAS ONE OF PROJECT GUTENBERG.*",
    r"Project Gutenberg's.*?, by.*?\n",
    r"Transcriber's note:.*?(?=\n\n|\Z)",
    r"Note du transcripteur\s*:.*?(?=\n\n|\Z)",
    r"End of the Project Gutenberg EBook.*",
    r"<<\s*The Project Gutenberg EBook.*>>",
    # Internet Archive notices
    r"Digitized\s+by\s+(the\s+)?Internet\s+Archive.*?(?=\n\n|\Z)",
    r"in\s+\d{4}\s+with\s+funding\s+from.*?(?=\n\n|\Z)",
    r"http[s]?://(www\.)?archive\.org/details/\S+",
    r"University\s+of\s+Ottawa|Boston\s+Public\s+Library|Kahle/Austin\s+Foundation|Getty\s+Research\s+Institute",
    # Wikisource boilerplate notices
    r"Extrait de «\s*https://\w+\.wikisource\.org/.*",
    r"Ce document a été scanné par.*",
]

def sanitize_filename(title: str) -> str:
    """Sanitize title for clean filesystem storage."""
    clean = re.sub(r'[\\/*?:"<>|]', '', title)
    clean = re.sub(r'\s+', ' ', clean).strip()
    return clean[:60] or "livre_domaine_public"

def apply_french_typography(text: str) -> str:
    """
    Applies classic French typographic rules:
    Inserts non-breaking space before double punctuation (: ; ! ? ») and after («).
    """
    if not text:
        return text
    # Space before : ; ! ? % »
    t = re.sub(r'[ \t]+([:;!?»%])', '\u00a0\\1', text)
    # Space after «
    t = re.sub(r'(«)[ \t]+', '\\1\u00a0', t)
    # Fix curly guillemets if any
    t = re.sub(r'[ \t]+([;!?])', '\u00a0\\1', t)
    return t

def generate_svg_cover(title: str, author: str) -> bytes:
    """
    Generates a publication-grade typographic SVG cover for books without covers.
    Infinite resolution on e-readers and Kindle.
    """
    clean_title = (title[:65] + '...') if len(title) > 65 else title
    clean_author = (author[:40] + '...') if len(author) > 40 else author
    
    # Split title into 2 lines if long
    lines = []
    words = clean_title.split()
    cur_line = []
    for w in words:
        if len(' '.join(cur_line + [w])) <= 22:
            cur_line.append(w)
        else:
            if cur_line:
                lines.append(' '.join(cur_line))
            cur_line = [w]
    if cur_line:
        lines.append(' '.join(cur_line))

    title_spans = []
    y_start = 600 - (len(lines) * 35)
    for i, l in enumerate(lines[:3]):
        y_pos = y_start + (i * 70)
        title_spans.append(f'<text x="600" y="{y_pos}" text-anchor="middle" font-family="Georgia, serif" font-size="52" font-weight="bold" fill="#f8fafc" letter-spacing="2">{l}</text>')

    title_markup = "\n".join(title_spans)

    svg_content = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1200 1800" width="1200" height="1800">
    <defs>
        <linearGradient id="bg" x1="0%" y1="0%" x2="100%" y2="100%">
            <stop offset="0%" stop-color="#090d16"/>
            <stop offset="50%" stop-color="#111827"/>
            <stop offset="100%" stop-color="#030712"/>
        </linearGradient>
    </defs>
    
    <!-- Background -->
    <rect width="1200" height="1800" fill="url(#bg)"/>
    
    <!-- Classic Double Frame -->
    <rect x="60" y="60" width="1080" height="1680" fill="none" stroke="#d97706" stroke-width="3" opacity="0.85"/>
    <rect x="80" y="80" width="1040" height="1640" fill="none" stroke="#d97706" stroke-width="1" opacity="0.4"/>
    
    <!-- Header Badge -->
    <text x="600" y="240" text-anchor="middle" font-family="Georgia, serif" font-size="24" fill="#d97706" letter-spacing="8" text-transform="uppercase">ÉDITION DU DOMAINE PUBLIC</text>
    <line x1="450" y1="270" x2="750" y2="270" stroke="#d97706" stroke-width="1.5" opacity="0.6"/>

    <!-- Book Title -->
    <g>
        {title_markup}
    </g>

    <!-- Ornament -->
    <text x="600" y="920" text-anchor="middle" font-family="Georgia, serif" font-size="36" fill="#d97706" opacity="0.75">❦ ❦ ❦</text>

    <!-- Author -->
    <text x="600" y="1120" text-anchor="middle" font-family="Georgia, serif" font-size="38" font-style="italic" fill="#cbd5e1" letter-spacing="3">{clean_author}</text>
    <line x1="480" y1="1160" x2="720" y2="1160" stroke="#cbd5e1" stroke-width="1" opacity="0.4"/>

    <!-- Footer -->
    <text x="600" y="1620" text-anchor="middle" font-family="sans-serif" font-size="20" fill="#64748b" letter-spacing="4">BIBLIOTHÈQUE LIBRE &amp; UNIVERSELLE</text>
</svg>"""
    return svg_content.encode("utf-8")

def clean_html_content(raw_html: str, lang: str = "fr") -> str:
    """
    Cleans raw chapter HTML:
    - Removes Gutenberg & Internet Archive disclaimers & boilerplates
    - Cleans OCR artifacts and noisy scan marks
    - Normalizes semantic typography and applies French non-breaking spaces
    """
    soup = BeautifulSoup(raw_html, "html.parser")

    # Remove script, style, noscript, iframe tags
    for tag in soup(["script", "style", "noscript", "iframe"]):
        tag.decompose()

    # Clean Gutenberg & Internet Archive boilerplates
    for pattern in GUTENBERG_DISCLAIMER_PATTERNS:
        for tag in soup.find_all(["div", "section", "p", "pre", "table", "center"]):
            if re.search(pattern, tag.get_text(), re.IGNORECASE | re.DOTALL):
                if len(tag.get_text().strip()) < 2500 or "archive.org" in tag.get_text().lower() or "gutenberg" in tag.get_text().lower() or "wikisource" in tag.get_text().lower():
                    tag.decompose()

    # Remove pg-header, pg-footer, pgheader, pgfooter, archive banners, wikisource headers
    for cl in ["pg-header", "pg-footer", "header", "footer", "boilerplate", "ia-metadata", "ws-noexport", "mw-editsection", "navigation-table"]:
        for el in soup.find_all(class_=lambda x: x and cl in str(x).lower()):
            el.decompose()
        for el in soup.find_all(id=lambda x: x and cl in str(x).lower()):
            el.decompose()

    # Remove isolated OCR noise paragraphs
    for p in soup.find_all(["p", "div"]):
        txt = p.get_text().strip()
        if re.match(r"^[\^<>\-_*#~=\d\s]{1,5}$", txt) or (len(txt) < 30 and "b1blioth" in txt.lower()):
            p.decompose()
        else:
            # Collapse excessive multiple whitespace in text
            if len(txt) > 0:
                clean_txt = re.sub(r'[ \t]{2,}', ' ', txt)
                if lang == "fr":
                    clean_txt = apply_french_typography(clean_txt)
                if p.string:
                    p.string.replace_with(clean_txt)

    # Clean inline styles
    for tag in soup.find_all(True):
        if tag.has_attr("style"):
            cleaned_style = re.sub(r'(font-[^;]+;|color:[^;]+;|background[^;]+;)', '', tag["style"]).strip()
            if cleaned_style:
                tag["style"] = cleaned_style
            else:
                del tag["style"]

    # Wrap body contents if missing
    body = soup.find("body")
    if not body:
        return f"<!DOCTYPE html><html><head><meta charset=\"utf-8\"/><title>Chapitre</title></head><body>{str(soup)}</body></html>"

    # Inject clean link to stylesheet in head
    head = soup.find("head")
    if not head:
        head = soup.new_tag("head")
        soup.insert(0, head)
    
    existing_css = head.find("link", rel="stylesheet")
    if existing_css:
        existing_css["href"] = "style.css"
    else:
        link_tag = soup.new_tag("link", rel="stylesheet", href="style.css", type="text/css")
        head.append(link_tag)

    return str(soup)

def is_document_item(item) -> bool:
    name = item.get_name().lower()
    if any(name.endswith(ext) for ext in [".xhtml", ".html", ".htm"]):
        return True
    mtype = (getattr(item, "media_type", "") or "").lower()
    if "html" in mtype or "xhtml" in mtype:
        return True
    return item.get_type() == ebooklib.ITEM_DOCUMENT

def is_image_item(item) -> bool:
    name = item.get_name().lower()
    if any(name.endswith(ext) for ext in [".jpg", ".jpeg", ".png", ".gif", ".svg", ".webp"]):
        return True
    mtype = (getattr(item, "media_type", "") or "").lower()
    return "image" in mtype or item.get_type() == ebooklib.ITEM_IMAGE

def clean_epub(source_epub_path: str, output_dir: str, title: Optional[str] = None, author: Optional[str] = None, lang: Optional[str] = None) -> str:
    """
    Takes an input EPUB file, cleans boilerplate, applies typography & CSS,
    generates cover if missing, and outputs a 100% Kindle & Kobo compatible EPUB3.
    """
    os.makedirs(output_dir, exist_ok=True)
    
    try:
        book = epub.read_epub(source_epub_path)
    except Exception as e:
        print(f"[Read EPUB Error] {e}")
        raise

    # Extract or override metadata
    titles = book.get_metadata('DC', 'title')
    embedded_title = titles[0][0] if titles else "Livre du Domaine Public"
    final_title = title if (title and not title.startswith("Gutenberg #")) else embedded_title
    
    creators = book.get_metadata('DC', 'creator')
    embedded_author = creators[0][0] if creators else "Auteur Inconnu"
    final_author = author if (author and author != "Inconnu") else embedded_author
    final_author = clean_author_name(final_author)

    final_lang = lang or "fr"
    languages = book.get_metadata('DC', 'language')
    if not lang and languages:
        final_lang = languages[0][0]

    # Create new clean EpubBook
    clean_book = epub.EpubBook()
    clean_book.set_identifier(str(uuid.uuid4()))
    clean_book.set_title(final_title)
    clean_book.set_language(final_lang)
    clean_book.add_author(final_author)
    clean_book.add_metadata('DC', 'rights', 'Domaine Public / Public Domain')
    clean_book.add_metadata('DC', 'publisher', 'Édition Domaine Public Propre')

    # Add Clean CSS
    css_item = epub.EpubItem(
        uid="style_nav",
        file_name="style.css",
        media_type="text/css",
        content=CLEAN_CSS.encode("utf-8")
    )
    clean_book.add_item(css_item)

    # Check for existing cover
    has_cover = False
    new_spine = ['nav']
    toc_items = []

    for item in book.get_items():
        fname_lower = item.get_name().lower()
        if fname_lower in ("toc.xhtml", "nav.xhtml", "toc.ncx", "content.opf"):
            continue

        if is_document_item(item):
            raw_content = item.get_content().decode("utf-8", errors="replace")
            cleaned_content = clean_html_content(raw_content, lang=final_lang)
            
            soup_check = BeautifulSoup(cleaned_content, "html.parser")
            body_tag = soup_check.find("body")
            body_text = body_tag.get_text().strip() if body_tag else soup_check.get_text().strip()

            if len(body_text) < 15:
                continue

            doc_title = getattr(item, "title", None) or "Chapitre"
            h1 = soup_check.find(["h1", "h2"])
            if h1 and h1.text.strip():
                doc_title = h1.text.strip()[:60]

            new_item = epub.EpubHtml(
                title=doc_title,
                file_name=item.get_name(),
                lang=final_lang
            )
            new_item.content = cleaned_content.encode("utf-8")
            
            if not new_item.get_body_content() or not new_item.get_body_content().strip():
                continue

            new_item.add_item(css_item)
            clean_book.add_item(new_item)
            new_spine.append(new_item)
            toc_items.append(new_item)

        elif is_image_item(item):
            if "cover" in item.get_name().lower():
                has_cover = True
            clean_book.add_item(item)
        elif item.get_type() in (ebooklib.ITEM_FONT, ebooklib.ITEM_AUDIO):
            clean_book.add_item(item)

    # If no cover was present, generate typographic cover
    if not has_cover:
        try:
            svg_data = generate_svg_cover(final_title, final_author)
            cover_item = epub.EpubItem(
                uid="cover_image",
                file_name="cover.svg",
                media_type="image/svg+xml",
                content=svg_data
            )
            clean_book.add_item(cover_item)
            
            # Add cover page
            cover_page = epub.EpubHtml(title="Couverture", file_name="cover.xhtml", lang=final_lang)
            cover_page.content = f"""<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xml:lang="{final_lang}">
<head><title>Couverture</title><style>body,html {{ margin:0; padding:0; height:100%; text-align:center; }} img {{ height:100%; max-width:100%; object-fit:contain; }}</style></head>
<body><img src="cover.svg" alt="{final_title}"/></body>
</html>""".encode("utf-8")
            clean_book.add_item(cover_page)
            new_spine.insert(1, cover_page)
        except Exception as e:
            print(f"[Cover Generation Warning] {e}")

    # Table of contents
    clean_book.toc = tuple(toc_items)
    clean_book.add_item(epub.EpubNcx())
    clean_book.add_item(epub.EpubNav())
    clean_book.spine = new_spine

    out_name = f"{sanitize_filename(final_title)} - {sanitize_filename(final_author)} (Édition Propre).epub"
    out_path = os.path.join(output_dir, out_name)

    epub.write_epub(out_path, clean_book, {})
    return out_path
