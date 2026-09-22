import os
import re
import time
from typing import Optional, Callable, Dict, List
import requests
from bs4 import BeautifulSoup, NavigableString
import ebooklib
from ebooklib import epub
from epub_cleaner import sanitize_filename, CLEAN_CSS
from concurrent.futures import ThreadPoolExecutor

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
}

# Translation cache to speed up and avoid redundant API calls
_TRANSLATION_CACHE: Dict[str, str] = {}

def _query_google_translate(text: str, target_lang: str = "fr", source_lang: str = "auto") -> Optional[str]:
    """
    Translates text using Google Translate public engine.
    High speed, high accuracy, and no daily quota cap.
    """
    sl = "auto" if source_lang in ("auto", "autodetect") else source_lang
    tl = target_lang
    url = "https://translate.googleapis.com/translate_a/single"
    params = {
        "client": "gtx",
        "sl": sl,
        "tl": tl,
        "dt": "t",
        "q": text
    }
    try:
        r = requests.get(url, params=params, headers=HEADERS, timeout=8)
        if r.status_code == 200:
            data = r.json()
            # data[0] contains array of [[translated_chunk, original_chunk, ...], ...]
            if data and isinstance(data, list) and len(data) > 0 and isinstance(data[0], list):
                translated_chunks = [item[0] for item in data[0] if item and len(item) > 0 and item[0]]
                return "".join(translated_chunks)
    except Exception:
        pass
    return None

def _query_mymemory(text: str, target_lang: str, source_lang: str = "auto") -> Optional[str]:
    """Helper query for MyMemory translation API."""
    s_lang = source_lang if source_lang != "auto" else "autodetect"
    langpair = f"{s_lang}|{target_lang}"
    
    url = "https://api.mymemory.translated.net/get"
    params = {
        "q": text,
        "langpair": langpair
    }
    
    try:
        r = requests.get(url, params=params, headers=HEADERS, timeout=8)
        if r.status_code == 200:
            data = r.json()
            translated = data.get("responseData", {}).get("translatedText")
            if translated and "MYMEMORY WARNING" not in translated:
                return translated
    except Exception:
        pass

    return None

def translate_text(text: str, target_lang: str = "fr", source_lang: str = "auto") -> str:
    """
    Multi-engine translator:
    1. Checks local memory cache
    2. Tries Google Translate engine (fast & no quota restriction)
    3. Falls back to MyMemory API
    4. Falls back to original text if unavailable
    """
    if not text or not text.strip():
        return text

    clean_text = text.strip()
    cache_key = f"{source_lang}->{target_lang}:{clean_text}"
    if cache_key in _TRANSLATION_CACHE:
        return _TRANSLATION_CACHE[cache_key]

    # For texts <= 1200 characters, translate in one shot
    if len(clean_text) <= 1200:
        # Try Google Translate first
        res = _query_google_translate(clean_text, target_lang, source_lang)
        if not res:
            # Fallback to MyMemory
            res = _query_mymemory(clean_text, target_lang, source_lang)
        
        final_res = res if res else clean_text
        _TRANSLATION_CACHE[cache_key] = final_res
        return final_res

    # For longer texts, chunk by sentence boundaries
    sentences = re.split(r'([.?!;:]\s+)', clean_text)
    translated_parts = []
    buffer = ""

    for part in sentences:
        if len(buffer) + len(part) < 800:
            buffer += part
        else:
            if buffer.strip():
                sub = _query_google_translate(buffer.strip(), target_lang, source_lang)
                if not sub:
                    sub = _query_mymemory(buffer.strip(), target_lang, source_lang)
                translated_parts.append(sub or buffer.strip())
            buffer = part

    if buffer.strip():
        sub = _query_google_translate(buffer.strip(), target_lang, source_lang)
        if not sub:
            sub = _query_mymemory(buffer.strip(), target_lang, source_lang)
        translated_parts.append(sub or buffer.strip())

    result = " ".join(translated_parts)
    _TRANSLATION_CACHE[cache_key] = result
    return result

def translate_text_mymemory(text: str, target_lang: str = "fr", source_lang: str = "auto") -> str:
    """Backward-compatibility wrapper pointing to multi-engine translate_text."""
    return translate_text(text, target_lang, source_lang)

def translate_html_content(html_str: str, target_lang: str, source_lang: str = "auto") -> str:
    """
    Translates HTML content (headings, paragraphs, blockquotes) in parallel
    while keeping tags and structure intact.
    """
    soup = BeautifulSoup(html_str, "html.parser")
    text_elements = soup.find_all(["h1", "h2", "h3", "h4", "p", "blockquote", "li"])

    valid_elements = [
        el for el in text_elements 
        if el.get_text().strip() and len(el.get_text().strip()) > 1 and not el.get_text().strip().isdigit()
    ]

    if not valid_elements:
        return str(soup)

    with ThreadPoolExecutor(max_workers=6) as executor:
        futures = [
            executor.submit(translate_text, el.get_text().strip(), target_lang, source_lang)
            for el in valid_elements
        ]
        for el, fut in zip(valid_elements, futures):
            try:
                translated_txt = fut.result()
                if translated_txt:
                    el.string = translated_txt
            except Exception:
                pass

    return str(soup)

def translate_epub(
    input_epub_path: str,
    output_dir: str,
    target_lang: str = "fr",
    source_lang: str = "auto",
    progress_callback: Optional[Callable[[int, str], None]] = None
) -> str:
    """
    Translates an entire EPUB into target_lang and produces a clean translated EPUB.
    """
    os.makedirs(output_dir, exist_ok=True)
    
    if progress_callback:
        progress_callback(5, "Ouverture de l'EPUB original...")

    book = epub.read_epub(input_epub_path)
    
    titles = book.get_metadata('DC', 'title')
    orig_title = titles[0][0] if titles else "Livre"
    creators = book.get_metadata('DC', 'creator')
    orig_author = creators[0][0] if creators else "Auteur Inconnu"

    if progress_callback:
        progress_callback(10, f"Traduction du titre: {orig_title}...")
    translated_title = translate_text(orig_title, target_lang=target_lang, source_lang=source_lang)

    new_book = epub.EpubBook()
    new_book.set_identifier(f"translated-{os.path.basename(input_epub_path)}")
    new_book.set_title(f"{translated_title} [Traduit en {target_lang.upper()}]")
    new_book.set_language(target_lang)
    new_book.add_author(f"{orig_author} (Traduction française/IA)")
    new_book.add_metadata('DC', 'rights', 'Domaine Public / Traduction libre')
    new_book.add_metadata('DC', 'publisher', 'Édition Domaine Public Traduite')

    css_item = epub.EpubItem(
        uid="style_trans",
        file_name="style.css",
        media_type="text/css",
        content=CLEAN_CSS.encode("utf-8")
    )
    new_book.add_item(css_item)

    from epub_cleaner import is_document_item, generate_svg_cover

    # Add translated typographic cover
    try:
        svg_data = generate_svg_cover(f"{translated_title} (Traduction)", orig_author)
        cover_item = epub.EpubItem(
            uid="cover_image",
            file_name="cover.svg",
            media_type="image/svg+xml",
            content=svg_data
        )
        new_book.add_item(cover_item)

        cover_page = epub.EpubHtml(title="Couverture", file_name="cover.xhtml", lang=target_lang)
        cover_page.content = f"""<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml" xml:lang="{target_lang}">
<head><title>Couverture</title><style>body,html {{ margin:0; padding:0; height:100%; text-align:center; }} img {{ height:100%; max-width:100%; object-fit:contain; }}</style></head>
<body><img src="cover.svg" alt="{translated_title}"/></body>
</html>""".encode("utf-8")
        new_book.add_item(cover_page)
        new_spine = ['nav', cover_page]
    except Exception:
        new_spine = ['nav']

    doc_items = [item for item in book.get_items() if is_document_item(item)]
    total_docs = len(doc_items)
    toc_items = []

    for i, item in enumerate(doc_items, 1):
        fname_lower = item.get_name().lower()
        if fname_lower in ("toc.xhtml", "nav.xhtml", "toc.ncx", "content.opf", "cover.xhtml"):
            continue

        percent = 15 + int((i / max(total_docs, 1)) * 80)
        chap_name = getattr(item, "title", None) or f"Chapitre {i}"
        
        if progress_callback:
            progress_callback(percent, f"Traduction du chapitre {i}/{total_docs} ({chap_name[:30]})...")

        raw_content = item.get_content().decode("utf-8", errors="replace")
        translated_content = translate_html_content(raw_content, target_lang=target_lang, source_lang=source_lang)
        translated_chap_name = translate_text(chap_name, target_lang=target_lang, source_lang=source_lang)

        new_item = epub.EpubHtml(
            title=translated_chap_name,
            file_name=item.get_name(),
            lang=target_lang
        )
        new_item.content = translated_content.encode("utf-8")
        
        if not new_item.get_body_content() or not new_item.get_body_content().strip():
            continue

        new_item.add_item(css_item)
        new_book.add_item(new_item)
        new_spine.append(new_item)
        toc_items.append(new_item)

    # Preserve original images
    for item in book.get_items():
        if item.get_type() == ebooklib.ITEM_IMAGE and "cover" not in item.get_name().lower():
            new_book.add_item(item)

    new_book.toc = tuple(toc_items)
    new_book.add_item(epub.EpubNcx())
    new_book.add_item(epub.EpubNav())
    new_book.spine = new_spine

    out_name = f"{sanitize_filename(translated_title)} [Traduit en {target_lang.upper()}] - {sanitize_filename(orig_author)}.epub"
    out_path = os.path.join(output_dir, out_name)

    if progress_callback:
        progress_callback(98, "Finalisation de l'EPUB traduit...")

    epub.write_epub(out_path, new_book, {})

    if progress_callback:
        progress_callback(100, f"Livre traduit et disponible : {out_name}")

    return out_path
