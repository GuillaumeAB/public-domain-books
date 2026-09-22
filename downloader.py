import os
import re
import urllib.parse
import requests
from typing import Dict, Any, Optional, Tuple
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
}

CACHE_DIR = os.path.join(os.path.dirname(__file__), "cache")
os.makedirs(CACHE_DIR, exist_ok=True)

def clean_author_name(raw_author: str) -> str:
    """Cleans noisy metadata author strings from libraries and catalogs."""
    if not raw_author or raw_author.strip() == "":
        return "Auteur Inconnu"
    # Remove lifespan dates like , 1842-1898 or (1842-1898)
    clean = re.sub(r'[\(\[]?\b\d{3,4}\s*-\s*\d{0,4}\b[\)\]]?', '', raw_author)
    clean = re.sub(r',\s*b\.\s*\d{4}', '', clean)
    clean = re.sub(r',\s*d\.\s*\d{4}', '', clean)
    # Split contributors if multiple
    if ";" in clean:
        clean = clean.split(";")[0].strip()
    elif clean.count(",") > 2:
        parts = [p.strip() for p in clean.split(",")]
        clean = f"{parts[0]}, {parts[1]}" if len(parts) >= 2 else parts[0]
    return clean.strip() or "Auteur Inconnu"

def download_gutenberg(book_id: str) -> Tuple[Optional[str], str, Dict[str, Any]]:
    """
    Downloads the best available format for a Gutenberg book.
    Prioritizes Gutendex direct endpoint for instant high-speed fetch, then mirrors.
    Returns: (filepath, format_type, metadata)
    """
    dest_epub = os.path.join(CACHE_DIR, f"gutenberg_{book_id}.epub")
    if os.path.exists(dest_epub) and os.path.getsize(dest_epub) > 2000:
        return dest_epub, "epub", {
            "id": f"gutenberg:{book_id}",
            "source": "Project Gutenberg",
            "title": f"Gutenberg #{book_id}",
            "author": "Inconnu",
            "language": "fr"
        }

    metadata = {
        "id": f"gutenberg:{book_id}",
        "source": "Project Gutenberg",
        "title": f"Gutenberg #{book_id}",
        "author": "Inconnu",
        "language": "fr",
        "cover_url": f"https://www.gutenberg.org/cache/epub/{book_id}/pg{book_id}.cover.medium.jpg"
    }

    # 1. Try Gutendex single book API for precise direct URL & metadata
    try:
        g_url = f"https://gutendex.com/books/{book_id}/"
        r_meta = requests.get(g_url, headers=HEADERS, timeout=6)
        if r_meta.status_code == 200:
            b_data = r_meta.json()
            metadata["title"] = b_data.get("title", metadata["title"])
            authors = b_data.get("authors", [])
            if authors:
                metadata["author"] = clean_author_name(authors[0].get("name", "Inconnu"))
            langs = b_data.get("languages", [])
            if langs:
                metadata["language"] = langs[0]
            formats = b_data.get("formats", {})
            if formats.get("image/jpeg"):
                metadata["cover_url"] = formats["image/jpeg"]
            
            # Direct EPUB url from Gutendex
            direct_epub_url = formats.get("application/epub+zip")
            if direct_epub_url:
                r = requests.get(direct_epub_url, headers=HEADERS, timeout=18, allow_redirects=True)
                if r.status_code == 200 and len(r.content) > 2000 and not r.text.startswith("<!DOCTYPE"):
                    with open(dest_epub, "wb") as f:
                        f.write(r.content)
                    return dest_epub, "epub", metadata
    except Exception:
        pass

    # 2. Try standard Gutenberg EPUB URLs
    epub_urls = [
        f"https://www.gutenberg.org/ebooks/{book_id}.epub3.images",
        f"https://www.gutenberg.org/ebooks/{book_id}.epub.images",
        f"https://www.gutenberg.org/ebooks/{book_id}.epub.noimages",
        f"https://www.gutenberg.org/cache/epub/{book_id}/pg{book_id}.epub",
        f"https://www.gutenberg.org/cache/epub/{book_id}/pg{book_id}-images.epub",
    ]

    for url in epub_urls:
        try:
            resp = requests.get(url, headers=HEADERS, timeout=12, allow_redirects=True)
            if resp.status_code == 200 and len(resp.content) > 2000 and not resp.text.startswith("<!DOCTYPE"):
                with open(dest_epub, "wb") as f:
                    f.write(resp.content)
                return dest_epub, "epub", metadata
        except Exception:
            pass

    # 3. Scrape Gutenberg book page for working links
    try:
        page_url = f"https://www.gutenberg.org/ebooks/{book_id}"
        resp = requests.get(page_url, headers=HEADERS, timeout=10)
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, "html.parser")
            t_el = soup.find("h1")
            if t_el:
                metadata["title"] = t_el.text.strip()
            
            for a in soup.find_all("a", href=True):
                h = a["href"]
                full_link = urllib.parse.urljoin("https://www.gutenberg.org", h)
                if ".epub" in h.lower() and not "send" in h.lower():
                    r = requests.get(full_link, headers=HEADERS, timeout=15, allow_redirects=True)
                    if r.status_code == 200 and len(r.content) > 2000 and not r.text.startswith("<!DOCTYPE"):
                        with open(dest_epub, "wb") as f:
                            f.write(r.content)
                        return dest_epub, "epub", metadata
                elif ("-images.html" in h.lower() or "-h.htm" in h.lower()) and not "help" in h.lower():
                    r = requests.get(full_link, headers=HEADERS, timeout=15, allow_redirects=True)
                    if r.status_code == 200 and len(r.content) > 1000:
                        dest_html = os.path.join(CACHE_DIR, f"gutenberg_{book_id}.html")
                        with open(dest_html, "w", encoding="utf-8", errors="replace") as f:
                            f.write(r.text)
                        return dest_html, "html", metadata
    except Exception:
        pass

    # 4. Fallback HTML
    html_urls = [
        f"https://www.gutenberg.org/ebooks/{book_id}.html.images",
        f"https://www.gutenberg.org/cache/epub/{book_id}/pg{book_id}-images.html",
        f"https://www.gutenberg.org/files/{book_id}/{book_id}-h/{book_id}-h.htm"
    ]
    for url in html_urls:
        try:
            resp = requests.get(url, headers=HEADERS, timeout=12, allow_redirects=True)
            if resp.status_code == 200 and len(resp.content) > 1000:
                dest_html = os.path.join(CACHE_DIR, f"gutenberg_{book_id}.html")
                with open(dest_html, "w", encoding="utf-8", errors="replace") as f:
                    f.write(resp.text)
                return dest_html, "html", metadata
        except Exception:
            pass

    # 5. Fallback plain text UTF-8
    txt_url = f"https://www.gutenberg.org/ebooks/{book_id}.txt.utf-8"
    try:
        resp = requests.get(txt_url, headers=HEADERS, timeout=12, allow_redirects=True)
        if resp.status_code == 200 and len(resp.content) > 500:
            dest_txt = os.path.join(CACHE_DIR, f"gutenberg_{book_id}.txt")
            with open(dest_txt, "w", encoding="utf-8", errors="replace") as f:
                f.write(resp.text)
            return dest_txt, "txt", metadata
    except Exception:
        pass

    return None, "none", metadata

def download_internet_archive(identifier: str) -> Tuple[Optional[str], str, Dict[str, Any]]:
    """
    Downloads book from Internet Archive metadata with cache and direct fallback.
    """
    metadata = {
        "id": f"ia:{identifier}",
        "source": "Internet Archive",
        "title": identifier,
        "author": "Inconnu",
        "language": "fr",
        "cover_url": f"https://archive.org/services/img/{identifier}"
    }

    cached_epub = os.path.join(CACHE_DIR, f"ia_{identifier}.epub")
    if os.path.exists(cached_epub) and os.path.getsize(cached_epub) > 2000:
        return cached_epub, "epub", metadata

    cached_txt = os.path.join(CACHE_DIR, f"ia_{identifier}.txt")
    if os.path.exists(cached_txt) and os.path.getsize(cached_txt) > 500:
        return cached_txt, "txt", metadata

    # 1. Try direct standard EPUB download URL
    direct_epub_url = f"https://archive.org/download/{identifier}/{identifier}.epub"
    try:
        r = requests.get(direct_epub_url, headers=HEADERS, timeout=12, allow_redirects=True)
        if r.status_code == 200 and len(r.content) > 3000 and not r.text.startswith("<!DOCTYPE"):
            with open(cached_epub, "wb") as f:
                f.write(r.content)
            return cached_epub, "epub", metadata
    except Exception:
        pass

    # 2. Query metadata endpoint
    try:
        meta_url = f"https://archive.org/metadata/{identifier}"
        r = requests.get(meta_url, headers=HEADERS, timeout=12)
        if r.status_code == 200:
            data = r.json()
            item_meta = data.get("metadata", {})
            metadata["title"] = item_meta.get("title", identifier)
            creator = item_meta.get("creator", "Auteur inconnu")
            if isinstance(creator, list):
                creator = ", ".join(str(c) for c in creator)
            metadata["author"] = clean_author_name(str(creator))
            metadata["language"] = str(item_meta.get("language", "fr"))
            metadata["year"] = item_meta.get("year")

            files = data.get("files", [])
            
            # Look for any .epub
            epub_files = [f for f in files if f.get("name", "").lower().endswith(".epub")]
            if epub_files:
                target = sorted(epub_files, key=lambda x: int(x.get("size", 0)), reverse=True)[0]
                fname = target["name"]
                dl_url = f"https://archive.org/download/{identifier}/{fname}"
                resp = requests.get(dl_url, headers=HEADERS, timeout=25, allow_redirects=True)
                if resp.status_code == 200 and len(resp.content) > 3000:
                    with open(cached_epub, "wb") as f:
                        f.write(resp.content)
                    return cached_epub, "epub", metadata

            # Look for djvu.txt or text
            txt_files = [f for f in files if f.get("name", "").lower().endswith(("_djvu.txt", ".txt"))]
            if txt_files:
                target = sorted(txt_files, key=lambda x: int(x.get("size", 0)), reverse=True)[0]
                fname = target["name"]
                dl_url = f"https://archive.org/download/{identifier}/{fname}"
                resp = requests.get(dl_url, headers=HEADERS, timeout=25, allow_redirects=True)
                if resp.status_code == 200 and len(resp.content) > 500:
                    with open(cached_txt, "w", encoding="utf-8", errors="replace") as f:
                        f.write(resp.text)
                    return cached_txt, "txt", metadata

    except Exception as e:
        print(f"[Download IA Metadata Error] {e}")

    # 3. Direct fallback to djvu.txt if metadata failed
    direct_txt_url = f"https://archive.org/download/{identifier}/{identifier}_djvu.txt"
    try:
        r = requests.get(direct_txt_url, headers=HEADERS, timeout=12, allow_redirects=True)
        if r.status_code == 200 and len(r.content) > 500 and not r.text.startswith("<!DOCTYPE"):
            with open(cached_txt, "w", encoding="utf-8", errors="replace") as f:
                f.write(r.text)
            return cached_txt, "txt", metadata
    except Exception:
        pass

    return None, "none", metadata

def download_wikisource(lang: str, page_title: str) -> Tuple[Optional[str], str, Dict[str, Any]]:
    """Downloads full text HTML from Wikisource API, cleaning wiki templates."""
    unquoted_title = urllib.parse.unquote(page_title)
    metadata = {
        "id": f"wikisource:{lang}:{page_title}",
        "source": "Wikisource",
        "title": unquoted_title.replace("_", " "),
        "author": "Domaine Public (Wikisource)",
        "language": lang,
        "cover_url": "https://upload.wikimedia.org/wikipedia/commons/thumb/4/4c/Wikisource-logo.svg/300px-Wikisource-logo.svg.png"
    }
    safe_name = re.sub(r'[^a-zA-Z0-9]', '_', unquoted_title)[:50]
    cached_html = os.path.join(CACHE_DIR, f"ws_{lang}_{safe_name}.html")
    if os.path.exists(cached_html) and os.path.getsize(cached_html) > 500:
        return cached_html, "html", metadata

    try:
        url = f"https://{lang}.wikisource.org/w/api.php"
        params = {
            "action": "parse",
            "page": unquoted_title,
            "prop": "text",
            "disabletoc": "1",
            "format": "json"
        }
        r = requests.get(url, params=params, headers=HEADERS, timeout=15)
        if r.status_code == 200:
            data = r.json()
            html_text = data.get("parse", {}).get("text", {}).get("*", "")
            if html_text:
                soup = BeautifulSoup(html_text, "html.parser")
                # Remove wikisource template headers, navigation, edit sections
                for el in soup.find_all(class_=["ws-noexport", "mw-editsection", "navigation-table", "headerContainer", "ws-header", "ws-summary"]):
                    el.decompose()
                
                clean_parsed = str(soup)
                with open(cached_html, "w", encoding="utf-8", errors="replace") as f:
                    f.write(f"<!DOCTYPE html><html><head><meta charset='utf-8'/><title>{unquoted_title}</title></head><body>{clean_parsed}</body></html>")
                return cached_html, "html", metadata
    except Exception as e:
        print(f"[Download Wikisource Error] {e}")

    return None, "none", metadata

def download_standard_ebooks(slug: str) -> Tuple[Optional[str], str, Dict[str, Any]]:
    """Downloads EPUB from Standard Ebooks."""
    clean_slug = slug.strip('/')
    metadata = {
        "id": f"se:{clean_slug}",
        "source": "Standard Ebooks",
        "title": clean_slug.replace('-', ' ').title(),
        "author": "Inconnu",
        "language": "en"
    }
    safe_name = re.sub(r'[^a-zA-Z0-9]', '_', clean_slug)[:50]
    cached_epub = os.path.join(CACHE_DIR, f"se_{safe_name}.epub")
    if os.path.exists(cached_epub) and os.path.getsize(cached_epub) > 2000:
        return cached_epub, "epub", metadata

    try:
        page_url = f"https://standardebooks.org/{clean_slug}"
        r = requests.get(page_url, headers=HEADERS, timeout=12)
        if r.status_code == 200:
            soup = BeautifulSoup(r.text, "html.parser")
            for a in soup.find_all("a", href=True):
                if a["href"].endswith(".epub") and not "kobo" in a["href"]:
                    full_url = urllib.parse.urljoin("https://standardebooks.org", a["href"])
                    r_epub = requests.get(full_url, headers=HEADERS, timeout=20)
                    if r_epub.status_code == 200:
                        with open(cached_epub, "wb") as f:
                            f.write(r_epub.content)
                        return cached_epub, "epub", metadata
    except Exception as e:
        print(f"[Download Standard Ebooks Error] {e}")

    return None, "none", metadata

def download_book(book_id_str: str) -> Tuple[Optional[str], str, Dict[str, Any]]:
    """
    Unified dispatcher taking gutenberg, ia, wikisource, or standard ebooks identifiers.
    """
    if book_id_str.startswith("gutenberg:"):
        gid = book_id_str.split(":", 1)[1]
        return download_gutenberg(gid)
    elif book_id_str.startswith("ia:"):
        ia_id = book_id_str.split(":", 1)[1]
        return download_internet_archive(ia_id)
    elif book_id_str.startswith("wikisource:"):
        parts = book_id_str.split(":", 2)
        ws_lang = parts[1] if len(parts) > 2 else "fr"
        ws_title = parts[2] if len(parts) > 2 else parts[1]
        return download_wikisource(ws_lang, ws_title)
    elif book_id_str.startswith("se:"):
        se_slug = book_id_str.split(":", 1)[1]
        return download_standard_ebooks(se_slug)
    else:
        if book_id_str.isdigit():
            return download_gutenberg(book_id_str)
        else:
            return download_internet_archive(book_id_str)
