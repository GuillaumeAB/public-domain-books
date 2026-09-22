import os
import re
import uuid
from typing import Optional, List, Dict
import ebooklib
from ebooklib import epub
from bs4 import BeautifulSoup
from epub_cleaner import CLEAN_CSS, sanitize_filename, GUTENBERG_DISCLAIMER_PATTERNS, generate_svg_cover, apply_french_typography

CHAPTER_PATTERNS = [
    r"^(CHAPITRE\s+[IVXLCDM\d]+.*?)$",
    r"^(CHAPTER\s+[IVXLCDM\d]+.*?)$",
    r"^(KAPITEL\s+[IVXLCDM\d]+.*?)$",
    r"^(CAPÍTULO\s+[IVXLCDM\d]+.*?)$",
    r"^(CAPITOLO\s+[IVXLCDM\d]+.*?)$",
    r"^(ACTE\s+[IVXLCDM\d]+.*?)$",
    r"^(SCÈNE\s+[IVXLCDM\d]+.*?)$",
    r"^(LIVRE\s+[IVXLCDM\d]+.*?)$",
    r"^(BOOK\s+[IVXLCDM\d]+.*?)$",
    r"^(PART\s+[IVXLCDM\d]+.*?)$",
    r"^(PARTIE\s+[IVXLCDM\d]+.*?)$",
    r"^([IVXLCDM]{1,8}\.?\s*)$"
]

def split_text_into_chapters(raw_text: str) -> List[Dict[str, str]]:
    """
    Parses plain text, removes boilerplates, and splits into chapters.
    """
    cleaned = raw_text
    for p in GUTENBERG_DISCLAIMER_PATTERNS:
        cleaned = re.sub(p, "", cleaned, flags=re.IGNORECASE | re.DOTALL)

    lines = cleaned.splitlines()
    chapters = []
    current_title = "Prologue / Début"
    current_lines = []

    combined_pattern = re.compile("|".join(CHAPTER_PATTERNS), re.IGNORECASE)

    for line in lines:
        stripped = line.strip()
        if combined_pattern.match(stripped) and len(stripped) < 80:
            if current_lines:
                text_block = "\n".join(current_lines).strip()
                if text_block:
                    chapters.append({"title": current_title, "text": text_block})
            current_title = stripped
            current_lines = []
        else:
            current_lines.append(line)

    if current_lines:
        text_block = "\n".join(current_lines).strip()
        if text_block:
            chapters.append({"title": current_title, "text": text_block})

    # If no chapters detected, chunk into manageable sections
    if len(chapters) <= 1:
        all_text = "\n".join(current_lines).strip()
        paragraphs = [p.strip() for p in all_text.split("\n\n") if p.strip()]
        if len(paragraphs) > 50:
            chapters = []
            chunk_size = 40
            for i in range(0, len(paragraphs), chunk_size):
                chunk_num = (i // chunk_size) + 1
                chapters.append({
                    "title": f"Section {chunk_num}",
                    "text": "\n\n".join(paragraphs[i:i+chunk_size])
                })
        else:
            chapters = [{"title": "Texte Intégral", "text": all_text}]

    return chapters

def text_to_clean_html(title: str, text: str, lang: str = "fr") -> str:
    """Converts a chapter text into semantic HTML paragraphs with French typographic rules."""
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    html_paragraphs = []
    for p in paragraphs:
        clean_p = " ".join(p.splitlines())
        clean_p = clean_p.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        if lang == "fr":
            clean_p = apply_french_typography(clean_p)
        html_paragraphs.append(f"<p>{clean_p}</p>")

    body_content = "\n".join(html_paragraphs)
    return f"""<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" lang="{lang}" xml:lang="{lang}">
<head>
    <meta charset="utf-8"/>
    <title>{title}</title>
    <link rel="stylesheet" href="style.css" type="text/css"/>
</head>
<body>
    <h1>{title}</h1>
    {body_content}
</body>
</html>"""

def build_epub_from_text(raw_text: str, title: str, author: str, output_dir: str, lang: str = "fr") -> str:
    """
    Builds a complete, validated, beautiful EPUB from raw text with automatic typographic cover.
    """
    os.makedirs(output_dir, exist_ok=True)
    chapters = split_text_into_chapters(raw_text)

    book = epub.EpubBook()
    book.set_identifier(str(uuid.uuid4()))
    book.set_title(title)
    book.set_language(lang)
    book.add_author(author)
    book.add_metadata('DC', 'rights', 'Domaine Public')
    book.add_metadata('DC', 'publisher', 'Édition Domaine Public Propre')

    # Stylesheet
    css_item = epub.EpubItem(
        uid="style_clean",
        file_name="style.css",
        media_type="text/css",
        content=CLEAN_CSS.encode("utf-8")
    )
    book.add_item(css_item)

    # Typographic cover
    try:
        svg_data = generate_svg_cover(title, author)
        cover_item = epub.EpubItem(
            uid="cover_image",
            file_name="cover.svg",
            media_type="image/svg+xml",
            content=svg_data
        )
        book.add_item(cover_item)

        cover_page = epub.EpubHtml(title="Couverture", file_name="cover.xhtml", lang=lang)
        cover_page.content = f"""<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xml:lang="{lang}">
<head><title>Couverture</title><style>body,html {{ margin:0; padding:0; height:100%; text-align:center; }} img {{ height:100%; max-width:100%; object-fit:contain; }}</style></head>
<body><img src="cover.svg" alt="{title}"/></body>
</html>""".encode("utf-8")
        book.add_item(cover_page)
        spine = ['nav', cover_page]
    except Exception:
        spine = ['nav']

    toc_items = []

    for idx, chap in enumerate(chapters, 1):
        html_content = text_to_clean_html(chap["title"], chap["text"], lang=lang)
        item = epub.EpubHtml(
            title=chap["title"],
            file_name=f"chap_{idx:03d}.xhtml",
            lang=lang
        )
        item.content = html_content.encode("utf-8")
        item.add_item(css_item)
        book.add_item(item)
        spine.append(item)
        toc_items.append(item)

    book.toc = tuple(toc_items)
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = spine

    out_name = f"{sanitize_filename(title)} - {sanitize_filename(author)} (Édition Propre).epub"
    out_path = os.path.join(output_dir, out_name)
    epub.write_epub(out_path, book, {})
    return out_path
