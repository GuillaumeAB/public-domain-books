import os
import re
import urllib.parse
from typing import List, Dict, Any, Optional
import requests
from bs4 import BeautifulSoup
from concurrent.futures import ThreadPoolExecutor

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,application/json;q=0.8,*/*;q=0.7",
    "Accept-Language": "fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7",
}

LANG_2_TO_3 = {
    "fr": "fre", "en": "eng", "de": "ger", "es": "spa", "it": "ita",
    "la": "lat", "el": "grc", "ru": "rus", "pt": "por", "nl": "dut",
    "zh": "chi", "ja": "jpn", "ar": "ara", "he": "heb", "pl": "pol"
}

LANG_NAMES = {
    "fr": "Français", "en": "English", "de": "Deutsch", "es": "Español",
    "it": "Italiano", "la": "Latin", "el": "Grec ancien", "ru": "Русский",
    "pt": "Português", "nl": "Nederlands", "zh": "Chinois", "ja": "Japonais",
    "ar": "Arabe", "he": "Hébreu", "pl": "Polonais"
}

def clean_author_string(author: str) -> str:
    """Format and clean author names, removing lifespan dates and catalog noise."""
    if not author or author.strip() == "":
        return "Auteur Inconnu"
    # Remove lifespan dates like (1842-1898) or , 1842-1898
    c = re.sub(r'[\(\[]?\b\d{3,4}\s*-\s*\d{0,4}\b[\)\]]?', '', author)
    c = re.sub(r',\s*b\.\s*\d{4}', '', c)
    c = re.sub(r',\s*d\.\s*\d{4}', '', c)
    # Convert 'Lastname, Firstname' to 'Firstname Lastname' if simple
    parts = [p.strip() for p in c.split(",") if p.strip()]
    if len(parts) == 2 and not any(k in parts[1].lower() for k in ["kniaz", "count", "sir", "abbé", "baron"]):
        c = f"{parts[1]} {parts[0]}"
    elif len(parts) > 2:
        c = f"{parts[1]} {parts[0]}"
    return re.sub(r'\s+', ' ', c).strip() or "Auteur Inconnu"

def search_gutendex(query: str, lang: Optional[str] = None, max_results: int = 25) -> List[Dict[str, Any]]:
    """
    Search Project Gutenberg via the fast, official Gutendex JSON API.
    Provides verified titles, direct download links, covers and download counts.
    """
    results = []
    try:
        params = {"search": query.strip()}
        if lang and lang != "all":
            params["languages"] = lang.lower()
            
        url = "https://gutendex.com/books/"
        resp = requests.get(url, params=params, headers=HEADERS, timeout=6)
        if resp.status_code != 200:
            return results

        data = resp.json()
        items = data.get("results", [])

        for book in items[:max_results]:
            book_id = str(book.get("id"))
            if not book_id:
                continue

            title = book.get("title", f"Gutenberg #{book_id}").strip()
            # Clean newline artifacts in titles
            title = re.sub(r'\s+', ' ', title)

            authors = book.get("authors", [])
            if authors:
                raw_auth = authors[0].get("name", "Auteur Inconnu")
                author = clean_author_string(raw_auth)
            else:
                author = "Auteur Inconnu"

            languages = book.get("languages", ["inconnu"])
            book_lang = languages[0] if languages else (lang or "inconnu")

            formats = book.get("formats", {})
            cover_url = formats.get("image/jpeg") or f"https://www.gutenberg.org/cache/epub/{book_id}/pg{book_id}.cover.medium.jpg"
            downloads = book.get("download_count", 0) or 0

            # Find best direct download URL
            direct_epub = formats.get("application/epub+zip")

            results.append({
                "id": f"gutenberg:{book_id}",
                "source_id": book_id,
                "source": "Project Gutenberg",
                "title": title,
                "author": author,
                "language": book_lang,
                "year": None,
                "downloads": downloads,
                "cover_url": cover_url,
                "direct_url": direct_epub,
                "web_url": f"https://www.gutenberg.org/ebooks/{book_id}",
                "description": f"Édition Project Gutenberg #{book_id} • {downloads} téléchargements"
            })
    except Exception as e:
        # Gutendex might occasionally timeout, fallback silently to web scraper
        pass

    return results

def search_gutenberg_scraper(query: str, lang: Optional[str] = None, max_results: int = 20) -> List[Dict[str, Any]]:
    """Fallback search on Project Gutenberg web catalog."""
    results = []
    try:
        search_term = query.strip()
        if lang and lang != "all":
            search_term += f" l.{lang.lower()}"
        
        url = f"https://www.gutenberg.org/ebooks/search/?query={urllib.parse.quote_plus(search_term)}"
        resp = requests.get(url, headers=HEADERS, timeout=8)
        if resp.status_code != 200:
            return results

        soup = BeautifulSoup(resp.text, "html.parser")
        booklinks = soup.find_all("li", class_="booklink")

        for item in booklinks[:max_results]:
            a_tag = item.find("a", class_="link")
            if not a_tag:
                continue
            href = a_tag.get("href", "")
            match = re.search(r"/ebooks/(\d+)", href)
            if not match:
                continue
            book_id = match.group(1)

            title_el = item.find("span", class_="title")
            raw_title = title_el.text.strip() if title_el else "Titre inconnu"
            
            item_lang = lang or "inconnu"
            lang_match = re.search(r"\(([^)]+)\)$", raw_title)
            if lang_match:
                item_lang = lang_match.group(1)
                clean_title = re.sub(r"\s*\([^)]+\)$", "", raw_title).strip()
            else:
                clean_title = raw_title

            subtitle_el = item.find("span", class_="subtitle")
            raw_author = subtitle_el.text.strip() if subtitle_el else "Auteur inconnu"
            author = clean_author_string(raw_author)

            extra_el = item.find("span", class_="extra")
            extra_text = extra_el.text.strip() if extra_el else ""
            downloads_match = re.search(r"(\d+)\s+downloads", extra_text)
            downloads = int(downloads_match.group(1)) if downloads_match else 0

            cover_img = item.find("img", class_="cover-thumb")
            if cover_img and cover_img.get("src"):
                cover_url = urllib.parse.urljoin("https://www.gutenberg.org", cover_img["src"])
            else:
                cover_url = f"https://www.gutenberg.org/cache/epub/{book_id}/pg{book_id}.cover.medium.jpg"

            results.append({
                "id": f"gutenberg:{book_id}",
                "source_id": book_id,
                "source": "Project Gutenberg",
                "title": clean_title,
                "author": author,
                "language": item_lang,
                "year": None,
                "downloads": downloads,
                "cover_url": cover_url,
                "web_url": f"https://www.gutenberg.org/ebooks/{book_id}",
                "description": f"Édition Project Gutenberg #{book_id} • {downloads} lectures"
            })
    except Exception as e:
        print(f"[Search Gutenberg Scraper Error] {e}")

    return results

def search_gutenberg(query: str, lang: Optional[str] = None, max_results: int = 20) -> List[Dict[str, Any]]:
    """Hybrid Project Gutenberg search: attempts Gutendex API first, then scraper."""
    results = search_gutendex(query, lang=lang, max_results=max_results)
    if not results:
        results = search_gutenberg_scraper(query, lang=lang, max_results=max_results)
    return results

def search_internet_archive(query: str, lang: Optional[str] = None, max_results: int = 20) -> List[Dict[str, Any]]:
    """Search Internet Archive for public domain books worldwide."""
    results = []
    try:
        clean_q = re.sub(r'["\']', '', query.strip())
        parts = [f'mediatype:texts', f'(title:("{clean_q}") OR creator:("{clean_q}") OR description:("{clean_q}"))']
        
        if lang and lang != "all":
            lang2 = lang.lower()
            lang3 = LANG_2_TO_3.get(lang2, lang2)
            parts.append(f'(language:{lang2} OR language:{lang3})')
        
        q_str = " AND ".join(parts)
        url = "https://archive.org/advancedsearch.php"
        params = {
            "q": q_str,
            "fl[]": ["identifier", "title", "creator", "year", "language", "description", "downloads"],
            "sort[]": "downloads desc",
            "rows": max_results,
            "output": "json"
        }
        resp = requests.get(url, params=params, headers=HEADERS, timeout=10)
        if resp.status_code != 200:
            return results

        data = resp.json()
        docs = data.get("response", {}).get("docs", [])

        for doc in docs:
            ident = doc.get("identifier")
            if not ident:
                continue
            title = doc.get("title", "Titre inconnu")
            creator = doc.get("creator", "Auteur inconnu")
            if isinstance(creator, list):
                creator = ", ".join(str(c) for c in creator)
            
            creator_clean = clean_author_string(str(creator))
            
            doc_lang = doc.get("language", lang or "inconnu")
            if isinstance(doc_lang, list):
                doc_lang = ", ".join(str(l) for l in doc_lang)

            year = doc.get("year")
            downloads = doc.get("downloads", 0) or 0
            desc = doc.get("description", "")
            if isinstance(desc, list):
                desc = " ".join(desc)
            desc_snippet = (desc[:160] + "...") if len(desc) > 160 else desc

            cover_url = f"https://archive.org/services/img/{ident}"

            results.append({
                "id": f"ia:{ident}",
                "source_id": ident,
                "source": "Internet Archive",
                "title": title,
                "author": creator_clean,
                "language": str(doc_lang),
                "year": year,
                "downloads": downloads,
                "cover_url": cover_url,
                "web_url": f"https://archive.org/details/{ident}",
                "description": desc_snippet or f"Document Internet Archive: {ident}"
            })
    except Exception as e:
        print(f"[Search Archive.org Error] {e}")

    return results

def search_wikisource(query: str, lang: Optional[str] = "fr", max_results: int = 15) -> List[Dict[str, Any]]:
    """
    Search Wikimedia Wikisource library for verified public domain texts.
    Uses namespace filtering (main namespace only) to eliminate noisy stubs and meta-pages.
    """
    results = []
    ws_lang = (lang if lang and lang != "all" else "fr").lower()
    
    try:
        url = f"https://{ws_lang}.wikisource.org/w/api.php"
        # Use query/search with namespace=0 for main namespace text
        params = {
            "action": "query",
            "list": "search",
            "srsearch": query.strip(),
            "srnamespace": "0",
            "srlimit": max_results,
            "format": "json"
        }
        resp = requests.get(url, params=params, headers=HEADERS, timeout=8)
        if resp.status_code != 200:
            return results

        data = resp.json()
        search_items = data.get("query", {}).get("search", [])

        for item in search_items:
            title = item.get("title", "")
            if not title:
                continue

            # Skip sub-pages, index pages or metadata
            if any(title.startswith(p) for p in ["Auteur:", "Author:", "Page:", "Livre:", "Category:", "Portail:", "Index:"]):
                continue

            clean_title = title.replace("_", " ")
            author = "Domaine Public (Wikisource)"
            if "(" in clean_title and clean_title.endswith(")"):
                parts = clean_title.rsplit("(", 1)
                clean_title = parts[0].strip()
                author = clean_author_string(parts[1].replace(")", "").strip())

            raw_snippet = item.get("snippet", "")
            # Remove html tags from snippet
            clean_snippet = re.sub(r'<[^>]+>', '', raw_snippet)

            page_url = f"https://{ws_lang}.wikisource.org/wiki/{urllib.parse.quote(title)}"

            results.append({
                "id": f"wikisource:{ws_lang}:{urllib.parse.quote(title)}",
                "source_id": title,
                "source": "Wikisource",
                "title": clean_title,
                "author": author,
                "language": ws_lang,
                "year": None,
                "downloads": 500,
                "cover_url": "https://upload.wikimedia.org/wikipedia/commons/thumb/4/4c/Wikisource-logo.svg/300px-Wikisource-logo.svg.png",
                "web_url": page_url,
                "description": clean_snippet or f"Texte authentifié Wikisource ({ws_lang.upper()})"
            })
    except Exception as e:
        print(f"[Search Wikisource Error] {e}")

    return results

def search_standard_ebooks(query: str, max_results: int = 10) -> List[Dict[str, Any]]:
    """Search Standard Ebooks for ultra-high quality curated public domain editions."""
    results = []
    try:
        url = f"https://standardebooks.org/ebooks/?query={urllib.parse.quote_plus(query.strip())}"
        resp = requests.get(url, headers=HEADERS, timeout=8)
        if resp.status_code != 200:
            return results

        soup = BeautifulSoup(resp.text, "html.parser")
        items = soup.find_all("li", class_="ebook")

        for item in items[:max_results]:
            a_tag = item.find("a")
            if not a_tag:
                continue
            href = a_tag.get("href", "")
            if not href.startswith("/ebooks/"):
                continue

            title_el = item.find("span", class_="title")
            title = title_el.text.strip() if title_el else a_tag.text.strip()

            author_el = item.find("span", class_="author")
            author = author_el.text.strip() if author_el else "Inconnu"
            author = clean_author_string(author)

            img_el = item.find("img")
            cover_url = urllib.parse.urljoin("https://standardebooks.org", img_el["src"]) if img_el else ""

            book_url = urllib.parse.urljoin("https://standardebooks.org", href)

            results.append({
                "id": f"se:{href.strip('/')}",
                "source_id": href.strip('/'),
                "source": "Standard Ebooks",
                "title": title,
                "author": author,
                "language": "en",
                "year": None,
                "downloads": 1000,
                "cover_url": cover_url,
                "web_url": book_url,
                "description": f"Édition typographique d'art Standard Ebooks"
            })
    except Exception as e:
        print(f"[Search Standard Ebooks Error] {e}")

    return results

def search_books(query: str, lang: Optional[str] = None, source: str = "all", max_results: int = 30) -> List[Dict[str, Any]]:
    """
    Unified public domain search across Gutenberg, Internet Archive, Wikisource, Standard Ebooks.
    Uses multi-threading to query all sources in parallel in under 1 second.
    """
    all_results = []
    tasks = []

    with ThreadPoolExecutor(max_workers=5) as executor:
        if source in ("all", "gutenberg"):
            tasks.append(executor.submit(search_gutenberg, query, lang, max_results))
        
        if source in ("all", "ia", "internet_archive"):
            tasks.append(executor.submit(search_internet_archive, query, lang, max_results))

        if source in ("all", "wikisource"):
            tasks.append(executor.submit(search_wikisource, query, lang, max_results))

        if source in ("all", "standard_ebooks", "standardebooks"):
            tasks.append(executor.submit(search_standard_ebooks, query, 10))

        for t in tasks:
            try:
                all_results.extend(t.result())
            except Exception as e:
                print(f"[Search Task Error] {e}")

    # Deduplicate and sort by popularity / downloads
    seen_ids = set()
    deduped = []
    for r in all_results:
        if r["id"] not in seen_ids:
            seen_ids.add(r["id"])
            deduped.append(r)

    deduped.sort(key=lambda x: x.get("downloads", 0), reverse=True)
    return deduped[:max_results]

def check_online_edition_in_target_lang(title: str, target_lang: str) -> Optional[Dict[str, Any]]:
    """
    Checks if an authentic human-translated / native public domain edition
    already exists online in target_lang before falling back to machine translation.
    """
    clean_title = re.sub(r'\[.*?\]|\(.*?\)', '', title).strip()
    candidates = []
    try:
        gb_res = search_gutenberg(clean_title, lang=target_lang, max_results=3)
        if gb_res:
            candidates.extend(gb_res)
        
        ws_res = search_wikisource(clean_title, lang=target_lang, max_results=3)
        if ws_res:
            candidates.extend(ws_res)
    except Exception:
        pass

    if candidates:
        return candidates[0]
    return None
