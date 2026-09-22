import os
import glob
import subprocess
import re
from typing import List, Dict, Any, Optional, Tuple
import ebooklib
from ebooklib import epub

EPUBS_DIR = os.path.join(os.path.dirname(__file__), "epubs")
os.makedirs(EPUBS_DIR, exist_ok=True)

def list_library_epubs() -> List[Dict[str, Any]]:
    """
    Returns list of all books (EPUB, PDF, TXT, HTML) available in the library.
    """
    patterns = ["*.epub", "*.pdf", "*.txt", "*.html"]
    files = []
    for pat in patterns:
        files.extend(glob.glob(os.path.join(EPUBS_DIR, pat)))

    books = []

    for fpath in files:
        fname = os.path.basename(fpath)
        stat = os.stat(fpath)
        size_mb = round(stat.st_size / (1024 * 1024), 2)
        size_str = f"{size_mb} Mo" if size_mb >= 0.1 else f"{round(stat.st_size / 1024, 1)} Ko"

        name_without_ext, ext = os.path.splitext(fname)
        fmt = ext.replace(".", "").upper()
        if fmt == "EPUB" and "kindle" in fname.lower():
            fmt = "KINDLE EPUB"

        title = name_without_ext
        author = "Domaine Public"
        lang = "fr"
        is_translated = "Traduit en" in fname
        has_cover = False

        if " - " in name_without_ext:
            parts = name_without_ext.split(" - ", 1)
            title = parts[0].strip()
            rest = parts[1].strip()
            author = re.sub(r'\(.*?\)', '', rest).strip()

        if ext.lower() == ".epub":
            try:
                book = epub.read_epub(fpath)
                t = book.get_metadata('DC', 'title')
                if t:
                    title = t[0][0]
                a = book.get_metadata('DC', 'creator')
                if a:
                    author = a[0][0]
                l = book.get_metadata('DC', 'language')
                if l:
                    lang = l[0][0]
                
                # Check for cover item
                for it in book.get_items():
                    if it.get_type() == ebooklib.ITEM_IMAGE or "cover" in it.get_name().lower():
                        has_cover = True
                        break
            except Exception:
                pass

        books.append({
            "filename": fname,
            "filepath": fpath,
            "format": fmt,
            "title": title,
            "author": author,
            "language": lang,
            "is_translated": is_translated,
            "has_cover": has_cover,
            "cover_url": f"/api/cover/{urllib_quote(fname)}" if has_cover else None,
            "size": size_str,
            "size_bytes": stat.st_size,
            "created_time": stat.st_mtime
        })

    # Sort newest first
    books.sort(key=lambda x: x["created_time"], reverse=True)
    return books

def urllib_quote(s: str) -> str:
    import urllib.parse
    return urllib.parse.quote(s)

def delete_library_book(filename: str) -> bool:
    """Deletes a book file from the local library."""
    safe_name = os.path.basename(filename)
    fpath = os.path.join(EPUBS_DIR, safe_name)
    if os.path.exists(fpath):
        try:
            os.remove(fpath)
            return True
        except Exception as e:
            print(f"[Delete Book Error] {e}")
            return False
    return False

def get_book_cover(filename: str) -> Tuple[Optional[bytes], Optional[str]]:
    """Extracts cover image from an EPUB in the library."""
    safe_name = os.path.basename(filename)
    fpath = os.path.join(EPUBS_DIR, safe_name)
    if not os.path.exists(fpath) or not safe_name.lower().endswith(".epub"):
        return None, None

    try:
        book = epub.read_epub(fpath)
        # Try to find cover image item
        for item in book.get_items():
            fname = item.get_name().lower()
            mtype = getattr(item, "media_type", "") or ""
            if "cover" in fname and ("image" in mtype or fname.endswith((".svg", ".jpg", ".jpeg", ".png", ".webp"))):
                content_type = mtype or ("image/svg+xml" if fname.endswith(".svg") else "image/jpeg")
                return item.get_content(), content_type

        # Fallback to any image item
        for item in book.get_items():
            if item.get_type() == ebooklib.ITEM_IMAGE:
                mtype = getattr(item, "media_type", "image/jpeg")
                return item.get_content(), mtype
    except Exception:
        pass

    return None, None

def open_epubs_folder():
    """Opens the epubs directory in Windows File Explorer."""
    try:
        subprocess.run(["explorer", os.path.abspath(EPUBS_DIR)], check=False)
        return True
    except Exception as e:
        print(f"[Open Folder Error] {e}")
        return False
