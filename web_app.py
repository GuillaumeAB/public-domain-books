import os
import shutil
import threading
import uuid
import urllib.parse
from typing import Optional, Dict, Any, List
from fastapi import FastAPI, Query, HTTPException, BackgroundTasks, Body, UploadFile, File
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse, Response
import uvicorn
from bs4 import BeautifulSoup
import ebooklib
from ebooklib import epub

from search_engine import search_books, LANG_NAMES, check_online_edition_in_target_lang
from downloader import download_book
from epub_cleaner import clean_epub, clean_html_content, is_document_item
from epub_builder import build_epub_from_text, split_text_into_chapters, text_to_clean_html
from translator import translate_epub, translate_html_content, translate_text
from format_exporter import convert_epub_to_format
from library_manager import list_library_epubs, open_epubs_folder, delete_library_book, get_book_cover, EPUBS_DIR

app = FastAPI(title="Bibliothèque Libre & Lecteur EPUB Universel")

JOBS: Dict[str, Dict[str, Any]] = {}

def extract_chapters_from_epub_file(file_path: str, max_chapters: int = 50) -> Dict[str, Any]:
    """Helper to extract structured chapters from an EPUB file."""
    book = epub.read_epub(file_path)
    
    titles = book.get_metadata('DC', 'title')
    title = titles[0][0] if titles else os.path.basename(file_path).replace(".epub", "")
    
    creators = book.get_metadata('DC', 'creator')
    author = creators[0][0] if creators else "Auteur inconnu"

    doc_items = [item for item in book.get_items() if is_document_item(item)]
    chapters = []

    for idx, doc in enumerate(doc_items[:max_chapters], 1):
        fname = doc.get_name().lower()
        if fname in ("toc.xhtml", "nav.xhtml", "toc.ncx", "content.opf", "cover.xhtml"):
            continue

        content = doc.get_content().decode("utf-8", errors="replace")
        cleaned = clean_html_content(content)
        soup = BeautifulSoup(cleaned, "html.parser")
        
        body = soup.find("body")
        body_html = str(body) if body else cleaned
        body_text = soup.get_text().strip()
        
        if len(body_text) < 15:
            continue

        chap_title = getattr(doc, "title", None)
        if not chap_title or chap_title.strip() == "":
            h1 = soup.find(["h1", "h2", "h3"])
            if h1 and h1.text.strip():
                chap_title = h1.text.strip()[:60]
            else:
                chap_title = f"Section {len(chapters) + 1}"

        chapters.append({
            "index": len(chapters),
            "title": chap_title,
            "html": body_html
        })

    return {
        "title": title,
        "author": author,
        "chapters": chapters
    }

@app.get("/api/search")
def api_search(q: str = Query(...), lang: Optional[str] = Query(None), source: str = Query("all")):
    """Searches books across Gutenberg, Internet Archive, Wikisource, Standard Ebooks."""
    results = search_books(q, lang=lang, source=source, max_results=25)
    return {"query": q, "count": len(results), "results": results}

@app.get("/api/languages")
def api_languages():
    """Returns available language filters."""
    return {"languages": LANG_NAMES}

@app.get("/api/library")
def api_library():
    """Lists all downloaded/generated EPUBs and books."""
    return {"books": list_library_epubs()}

@app.delete("/api/book/{filename}")
def api_delete_book(filename: str):
    """Deletes a book from the local library."""
    success = delete_library_book(filename)
    if not success:
        raise HTTPException(status_code=404, detail="Fichier introuvable ou impossible à supprimer")
    return {"success": True, "filename": filename}

@app.get("/api/cover/{filename}")
def api_cover(filename: str):
    """Returns cover image of a book if available."""
    content, media_type = get_book_cover(filename)
    if not content:
        raise HTTPException(status_code=404, detail="Couverture non disponible")
    return Response(content=content, media_type=media_type)

@app.post("/api/upload")
async def api_upload_book(file: UploadFile = File(...)):
    """Uploads a personal EPUB or TXT file into the library."""
    fname = os.path.basename(file.filename)
    ext = os.path.splitext(fname)[1].lower()
    if ext not in (".epub", ".txt", ".pdf", ".html"):
        raise HTTPException(status_code=400, detail="Format de fichier non pris en charge (utilisez .epub, .txt, .pdf, .html)")
    
    dest_path = os.path.join(EPUBS_DIR, fname)
    with open(dest_path, "wb") as f:
        shutil.copyfileobj(file.file, f)
    
    return {"success": True, "filename": fname}

@app.post("/api/open-folder")
def api_open_folder():
    """Opens the epubs directory in Windows File Explorer."""
    success = open_epubs_folder()
    return {"success": success, "path": os.path.abspath(EPUBS_DIR)}

@app.get("/api/download/{filename}")
def api_download(filename: str):
    """Downloads a book file in any format (EPUB, PDF, TXT, HTML)."""
    fpath = os.path.join(EPUBS_DIR, filename)
    if not os.path.exists(fpath):
        raise HTTPException(status_code=404, detail="Fichier non trouvé")
    
    ext = os.path.splitext(filename)[1].lower()
    media_types = {
        ".epub": "application/epub+zip",
        ".pdf": "application/pdf",
        ".txt": "text/plain; charset=utf-8",
        ".html": "text/html; charset=utf-8",
        ".htm": "text/html; charset=utf-8",
    }
    media_type = media_types.get(ext, "application/octet-stream")
    return FileResponse(fpath, media_type=media_type, filename=filename)

@app.get("/api/check-language")
def api_check_language(title: str = Query(...), target_lang: str = Query(...)):
    """Checks if an authentic online edition exists in target_lang."""
    match = check_online_edition_in_target_lang(title, target_lang)
    return {"exists": match is not None, "edition": match}

@app.get("/api/preview")
def api_preview(book_id: str = Query(...)):
    """Downloads and extracts preview chapters for in-browser reading."""
    dl_path, fmt, meta = download_book(book_id)
    if not dl_path or not os.path.exists(dl_path):
        raise HTTPException(status_code=404, detail="Livre introuvable au téléchargement. Le serveur source est peut-être inaccessible.")

    if fmt == "epub":
        try:
            data = extract_chapters_from_epub_file(dl_path)
            if not data.get("title") or data["title"].startswith(("Gutenberg #", "ia_", "ia:")):
                data["title"] = meta.get("title", data.get("title", "Livre"))
            if not data.get("author") or data["author"] in ("Auteur inconnu", "Inconnu"):
                data["author"] = meta.get("author", "Auteur Inconnu")
            return data
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Erreur d'extraction EPUB: {e}")

    elif fmt in ("html", "txt"):
        with open(dl_path, "r", encoding="utf-8", errors="replace") as f:
            raw_text = f.read()
        
        parsed_chapters = split_text_into_chapters(raw_text)
        chapters = []
        for idx, c in enumerate(parsed_chapters[:40]):
            html_chunk = text_to_clean_html(c["title"], c["text"], lang=meta.get("language", "fr"))
            chapters.append({
                "index": idx,
                "title": c["title"],
                "html": html_chunk
            })

        return {
            "title": meta.get("title", "Livre"),
            "author": meta.get("author", "Auteur inconnu"),
            "chapters": chapters
        }

    raise HTTPException(status_code=400, detail="Format non supporté pour la prévisualisation")

@app.get("/api/preview/{book_id:path}")
def api_preview_legacy(book_id: str):
    return api_preview(book_id=book_id)

@app.get("/api/read-local/{filename}")
def api_read_local(filename: str):
    """Reads a generated EPUB directly from the local library."""
    fpath = os.path.join(EPUBS_DIR, filename)
    if not os.path.exists(fpath):
        raise HTTPException(status_code=404, detail="Livre introuvable dans la bibliothèque")

    try:
        return extract_chapters_from_epub_file(fpath)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur de lecture: {e}")

@app.post("/api/translate-chapter")
def api_translate_chapter(payload: Dict[str, Any] = Body(...)):
    """Translates a single chapter on-the-fly for real-time bilingual reading."""
    html_content = payload.get("html", "")
    target_lang = payload.get("target_lang", "fr")
    if not html_content:
        return {"translated_html": ""}

    translated = translate_html_content(html_content, target_lang=target_lang)
    return {"translated_html": translated}

def process_generate_job(job_id: str, book_id: str, clean_only: bool, target_lang: Optional[str], output_format: str = "epub"):
    try:
        JOBS[job_id]["status"] = "downloading"
        JOBS[job_id]["message"] = "Téléchargement du livre source..."
        JOBS[job_id]["percent"] = 20

        dl_path, fmt, meta = download_book(book_id)
        if not dl_path or not os.path.exists(dl_path):
            JOBS[job_id]["status"] = "error"
            JOBS[job_id]["message"] = "Échec du téléchargement du document source."
            return

        JOBS[job_id]["percent"] = 50
        JOBS[job_id]["message"] = "Nettoyage et mise en page typographique..."

        clean_path = None
        if fmt == "epub":
            clean_path = clean_epub(
                source_epub_path=dl_path,
                output_dir=EPUBS_DIR,
                title=meta.get("title"),
                author=meta.get("author"),
                lang=meta.get("language")
            )
        elif fmt == "txt":
            with open(dl_path, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
            clean_path = build_epub_from_text(
                raw_text=content,
                title=meta.get("title", "Livre"),
                author=meta.get("author", "Inconnu"),
                output_dir=EPUBS_DIR,
                lang=meta.get("language", "fr")
            )
        elif fmt == "html":
            with open(dl_path, "r", encoding="utf-8", errors="replace") as f:
                soup = BeautifulSoup(f.read(), "html.parser")
            clean_path = build_epub_from_text(
                raw_text=soup.get_text(),
                title=meta.get("title", "Livre"),
                author=meta.get("author", "Inconnu"),
                output_dir=EPUBS_DIR,
                lang=meta.get("language", "fr")
            )

        if not clean_path or not os.path.exists(clean_path):
            JOBS[job_id]["status"] = "error"
            JOBS[job_id]["message"] = "Impossible de générer le fichier EPUB propre."
            return

        # Handle translation if requested
        if target_lang and target_lang != "none":
            JOBS[job_id]["status"] = "translating"
            JOBS[job_id]["message"] = f"Traduction du livre en {target_lang.upper()}..."

            def on_progress(pct, msg):
                JOBS[job_id]["percent"] = pct
                JOBS[job_id]["message"] = msg

            trans_path = translate_epub(
                input_epub_path=clean_path,
                output_dir=EPUBS_DIR,
                target_lang=target_lang,
                progress_callback=on_progress
            )
            final_file = trans_path
        else:
            final_file = clean_path

        # Handle format conversion if needed
        if output_format and output_format not in ("epub", "kindle_epub", "kindle"):
            JOBS[job_id]["status"] = "converting"
            JOBS[job_id]["percent"] = 90
            JOBS[job_id]["message"] = f"Conversion au format {output_format.upper()}..."
            final_file = convert_epub_to_format(final_file, output_format, EPUBS_DIR)

        format_names = {
            "epub": "EPUB Propre",
            "kindle_epub": "EPUB Kindle",
            "pdf_ereader": "PDF Liseuse (6\")",
            "pdf_a4": "PDF A4",
            "txt": "Texte brut (TXT)",
            "html": "Document HTML"
        }
        fmt_label = format_names.get(output_format, "Livre")

        JOBS[job_id]["status"] = "done"
        JOBS[job_id]["percent"] = 100
        JOBS[job_id]["message"] = f"{fmt_label} prêt avec succès !"
        JOBS[job_id]["filename"] = os.path.basename(final_file)
        JOBS[job_id]["filepath"] = final_file
        JOBS[job_id]["format"] = output_format

    except Exception as e:
        JOBS[job_id]["status"] = "error"
        JOBS[job_id]["message"] = f"Erreur : {str(e)}"

@app.post("/api/generate")
def api_generate(
    book_id: str = Query(...),
    target_lang: Optional[str] = Query(None),
    format: str = Query("epub"),
    background_tasks: BackgroundTasks = BackgroundTasks()
):
    """Starts an asynchronous job to download, clean, and optionally translate a book in chosen format."""
    job_id = str(uuid.uuid4())
    JOBS[job_id] = {
        "id": job_id,
        "book_id": book_id,
        "format": format,
        "status": "queued",
        "percent": 5,
        "message": "Préparation...",
        "filename": None
    }
    background_tasks.add_task(process_generate_job, job_id, book_id, target_lang is None, target_lang, format)
    return {"job_id": job_id}

@app.get("/api/job/{job_id}")
def api_job_status(job_id: str):
    job = JOBS.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job non trouvé")
    return job

# Main Single Page App UI
@app.get("/", response_class=HTMLResponse)
def get_ui():
    return """<!DOCTYPE html>
<html lang="fr" class="h-full bg-slate-950 text-slate-100">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Bibliothèque Libre & Liseuse EPUB</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.1/css/all.min.css">
    <link href="https://fonts.googleapis.com/css2?family=Cinzel:wght@600;800&family=Inter:wght@300;400;500;600;700&family=Merriweather:ital,wght@0,300;0,400;0,700;1,300&family=JetBrains+Mono:wght@400&display=swap" rel="stylesheet">
    <style>
        .font-cinzel { font-family: 'Cinzel', serif; }
        .font-merriweather { font-family: 'Merriweather', Georgia, serif; }
        .font-inter { font-family: 'Inter', sans-serif; }
        .font-mono-reading { font-family: 'JetBrains Mono', monospace; }

        .custom-scroll::-webkit-scrollbar { width: 7px; height: 7px; }
        .custom-scroll::-webkit-scrollbar-thumb { background: #334155; border-radius: 4px; }
        .custom-scroll::-webkit-scrollbar-track { background: transparent; }

        /* Reader Themes */
        .reader-dark { background-color: #0f172a; color: #e2e8f0; }
        .reader-dark p { color: #cbd5e1; }
        
        .reader-sepia { background-color: #fbf0d9; color: #2e2115; }
        .reader-sepia h1, .reader-sepia h2, .reader-sepia h3 { color: #1e1308 !important; }
        .reader-sepia p { color: #3b2c1d !important; }
        .reader-sepia blockquote { border-left-color: #bfa57d !important; }

        .reader-light { background-color: #ffffff; color: #1e293b; }
        .reader-light h1, .reader-light h2, .reader-light h3 { color: #0f172a !important; }
        .reader-light p { color: #334155 !important; }

        /* Reader typography styling */
        #reader-body p {
            margin-bottom: 0.9em;
            text-indent: 1.6em;
            line-height: inherit;
        }
        #reader-body h1, #reader-body h2, #reader-body h3 {
            text-align: center;
            font-weight: 700;
            margin-top: 1.5em;
            margin-bottom: 0.8em;
            text-indent: 0;
        }
        #reader-body h1 { font-size: 1.8em; }
        #reader-body h2 { font-size: 1.4em; }
        #reader-body blockquote {
            margin: 1.5em 2em;
            padding-left: 1em;
            border-left: 3px solid #64748b;
            font-style: italic;
            text-indent: 0;
        }
    </style>
</head>
<body class="h-full flex flex-col font-sans selection:bg-amber-500/30 selection:text-amber-200">

    <!-- Header / Navbar -->
    <header class="bg-gradient-to-r from-slate-900 via-indigo-950 to-slate-900 border-b border-indigo-900/40 px-6 py-4 flex items-center justify-between shadow-2xl z-20">
        <div class="flex items-center space-x-4">
            <div class="w-11 h-11 rounded-2xl bg-gradient-to-tr from-amber-500 to-amber-300 flex items-center justify-center shadow-lg shadow-amber-500/25 text-slate-950 font-bold text-2xl transform hover:scale-105 transition-transform">
                <i class="fa-solid fa-book-open"></i>
            </div>
            <div>
                <h1 class="text-xl font-bold font-cinzel tracking-wider text-amber-200 flex items-center gap-2">
                    BIBLIOTHÈQUE LIBRE
                    <span class="text-[10px] tracking-normal font-sans font-semibold bg-amber-400/20 text-amber-300 border border-amber-400/30 px-2 py-0.5 rounded-full">v2.5 Pro</span>
                </h1>
                <p class="text-xs text-indigo-300">Recherche Domaine Public • Édition EPUB Propre • Traducteur & Liseuse Intégrée</p>
            </div>
        </div>

        <nav class="flex items-center space-x-3">
            <button onclick="switchTab('search')" id="tab-btn-search" class="px-4 py-2 rounded-xl text-sm font-semibold transition-all bg-indigo-600/30 text-amber-300 border border-indigo-500/50 shadow-inner">
                <i class="fa-solid fa-magnifying-glass mr-2"></i>Rechercher
            </button>
            <button onclick="switchTab('library')" id="tab-btn-library" class="px-4 py-2 rounded-xl text-sm font-semibold transition-all text-slate-300 hover:bg-slate-800 border border-transparent">
                <i class="fa-solid fa-bookmark mr-2 text-amber-400"></i>Ma Bibliothèque (<span id="library-count">0</span>)
            </button>
            <label class="px-4 py-2 rounded-xl text-sm font-medium text-slate-300 hover:text-white bg-slate-800/80 hover:bg-slate-700 transition-all border border-slate-700 shadow cursor-pointer" title="Importer un fichier EPUB ou TXT depuis votre ordinateur">
                <i class="fa-solid fa-file-arrow-up mr-2 text-amber-400"></i>Importer
                <input type="file" id="upload-input" accept=".epub,.txt,.pdf,.html" class="hidden" onchange="handleFileUpload(event)">
            </label>
            <button onclick="openEpubsFolder()" class="px-4 py-2 rounded-xl text-sm font-medium text-slate-300 hover:text-white bg-slate-800/80 hover:bg-slate-700 transition-all border border-slate-700 shadow" title="Ouvrir le dossier des EPUB sur votre ordinateur">
                <i class="fa-regular fa-folder-open mr-2 text-amber-400"></i>Dossier EPUB
            </button>
        </nav>
    </header>

    <!-- Main Workspace -->
    <main class="flex-1 overflow-y-auto custom-scroll p-6 max-w-7xl mx-auto w-full">

        <!-- SEARCH TAB -->
        <section id="tab-search" class="space-y-6">
            <!-- Search & Filters Banner -->
            <div class="bg-slate-900/90 backdrop-blur-md border border-slate-800/80 rounded-3xl p-6 shadow-2xl relative overflow-hidden">
                <div class="absolute -right-10 -top-10 w-48 h-48 bg-amber-500/5 rounded-full blur-3xl pointer-events-none"></div>

                <form id="search-form" onsubmit="handleSearch(event)" class="space-y-4 relative z-10">
                    <div class="flex flex-col md:flex-row gap-3">
                        <div class="relative flex-1">
                            <i class="fa-solid fa-magnifying-glass absolute left-4 top-1/2 -translate-y-1/2 text-slate-400 text-lg"></i>
                            <input type="text" id="search-input" placeholder="Titre, auteur, mot-clé (ex: Victor Hugo, Baudelaire, Homère, Dante, Dostoïevski, Platon...)" 
                                   class="w-full pl-12 pr-4 py-3.5 bg-slate-950/80 border border-slate-700 rounded-2xl focus:outline-none focus:border-amber-400 focus:ring-2 focus:ring-amber-400/20 text-white placeholder-slate-500 shadow-inner text-base">
                        </div>
                        <button type="submit" class="px-8 py-3.5 bg-gradient-to-r from-amber-500 to-amber-600 hover:from-amber-400 hover:to-amber-500 text-slate-950 font-bold rounded-2xl shadow-lg shadow-amber-500/20 transition-all transform active:scale-95 flex items-center justify-center space-x-2">
                            <span>Rechercher</span>
                            <i class="fa-solid fa-arrow-right text-sm"></i>
                        </button>
                    </div>

                    <!-- Filter badges row -->
                    <div class="flex flex-wrap items-center gap-4 text-xs pt-2 border-t border-slate-800/60">
                        <div class="flex items-center space-x-2">
                            <span class="text-slate-400 font-medium"><i class="fa-solid fa-language mr-1 text-amber-400"></i>Langue d'origine :</span>
                            <select id="filter-lang" class="bg-slate-950 border border-slate-700 rounded-xl px-3 py-1.5 text-slate-200 focus:outline-none focus:border-amber-400 font-medium">
                                <option value="all">Toutes les langues</option>
                                <option value="fr" selected>Français</option>
                                <option value="en">English (Anglais)</option>
                                <option value="de">Deutsch (Allemand)</option>
                                <option value="es">Español (Espagnol)</option>
                                <option value="it">Italiano (Italien)</option>
                                <option value="la">Latin</option>
                                <option value="el">Grec ancien</option>
                                <option value="ru">Русский (Russe)</option>
                                <option value="pt">Português (Portugais)</option>
                                <option value="ar">العربية (Arabe)</option>
                                <option value="zh">中文 (Chinois)</option>
                            </select>
                        </div>

                        <div class="flex items-center space-x-2">
                            <span class="text-slate-400 font-medium"><i class="fa-solid fa-database mr-1 text-amber-400"></i>Catalogue :</span>
                            <select id="filter-source" class="bg-slate-950 border border-slate-700 rounded-xl px-3 py-1.5 text-slate-200 focus:outline-none focus:border-amber-400 font-medium">
                                <option value="all" selected>Toutes les sources (Gutenberg, Archive.org, Wikisource, Standard Ebooks)</option>
                                <option value="gutenberg">Project Gutenberg uniquement</option>
                                <option value="ia">Internet Archive uniquement</option>
                                <option value="wikisource">Wikisource (Textes authentifiés)</option>
                                <option value="standard_ebooks">Standard Ebooks (Mise en page d'art)</option>
                            </select>
                        </div>

                        <!-- Quick suggestions -->
                        <div class="flex items-center space-x-1.5 ml-auto text-slate-400">
                            <span class="text-xs text-slate-500">Exemples :</span>
                            <button type="button" onclick="quickSearch('Baudelaire Fleurs du mal')" class="px-2.5 py-1 bg-slate-800/80 hover:bg-slate-700 text-amber-200/90 rounded-lg border border-slate-700 transition">Baudelaire</button>
                            <button type="button" onclick="quickSearch('Candide Voltaire')" class="px-2.5 py-1 bg-slate-800/80 hover:bg-slate-700 text-amber-200/90 rounded-lg border border-slate-700 transition">Voltaire</button>
                            <button type="button" onclick="quickSearch('The Raven Poe')" class="px-2.5 py-1 bg-slate-800/80 hover:bg-slate-700 text-amber-200/90 rounded-lg border border-slate-700 transition">Poe</button>
                            <button type="button" onclick="quickSearch('Dante Divine Comedie')" class="px-2.5 py-1 bg-slate-800/80 hover:bg-slate-700 text-amber-200/90 rounded-lg border border-slate-700 transition">Dante</button>
                        </div>
                    </div>
                </form>
            </div>

            <!-- Loading Spinner -->
            <div id="search-loading" class="hidden py-20 text-center space-y-4">
                <div class="inline-block animate-spin text-amber-400 text-5xl">
                    <i class="fa-solid fa-circle-notch"></i>
                </div>
                <p class="text-slate-300 text-sm font-medium">Exploration des catalogues du domaine public mondial...</p>
            </div>

            <!-- Search Results Grid -->
            <div id="results-container" class="space-y-4">
                <div id="results-count" class="text-sm text-slate-400 font-semibold px-1"></div>
                <div id="results-grid" class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6"></div>
            </div>

            <!-- Welcome / Empty state -->
            <div id="search-empty" class="py-20 text-center space-y-4 border border-dashed border-slate-800/80 rounded-3xl bg-slate-900/30">
                <div class="w-20 h-20 mx-auto rounded-3xl bg-slate-900 flex items-center justify-center text-amber-400 text-3xl shadow-inner border border-slate-800">
                    <i class="fa-solid fa-feather-pointed"></i>
                </div>
                <div>
                    <h3 class="text-xl font-bold text-slate-200">Explorez les trésors de la littérature mondiale</h3>
                    <p class="text-sm text-slate-400 max-w-lg mx-auto mt-2 leading-relaxed">Tapez un auteur, une œuvre ou un mot-clé pour prévisualiser instantanément dans le lecteur intégré, télécharger une édition propre ou traduire automatiquement.</p>
                </div>
            </div>
        </section>

        <!-- LIBRARY TAB -->
        <section id="tab-library" class="hidden space-y-6">
            <div class="flex items-center justify-between bg-slate-900/80 border border-slate-800 p-6 rounded-3xl shadow-xl flex-wrap gap-4">
                <div>
                    <h2 class="text-xl font-bold text-white flex items-center">
                        <i class="fa-solid fa-bookmark text-amber-400 mr-2.5"></i>Vos Livres & Documents Disponibles
                    </h2>
                    <p class="text-xs text-slate-400 mt-1">Dossier : <span class="font-mono text-slate-300">epubs/</span></p>
                </div>

                <div class="flex items-center space-x-2">
                    <button onclick="filterLibrary('all')" class="lib-filter-btn px-3 py-1.5 rounded-xl text-xs font-semibold bg-amber-500/20 text-amber-300 border border-amber-500/40" data-filter="all">Tous</button>
                    <button onclick="filterLibrary('EPUB')" class="lib-filter-btn px-3 py-1.5 rounded-xl text-xs font-medium text-slate-400 hover:text-white" data-filter="EPUB">EPUB</button>
                    <button onclick="filterLibrary('PDF')" class="lib-filter-btn px-3 py-1.5 rounded-xl text-xs font-medium text-slate-400 hover:text-white" data-filter="PDF">PDF</button>
                    <button onclick="filterLibrary('TXT')" class="lib-filter-btn px-3 py-1.5 rounded-xl text-xs font-medium text-slate-400 hover:text-white" data-filter="TXT">TXT</button>
                    <button onclick="filterLibrary('HTML')" class="lib-filter-btn px-3 py-1.5 rounded-xl text-xs font-medium text-slate-400 hover:text-white" data-filter="HTML">HTML</button>
                </div>
            </div>

            <div id="library-grid" class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6"></div>

            <div id="library-empty" class="hidden py-20 text-center space-y-4 border border-dashed border-slate-800/80 rounded-3xl bg-slate-900/30">
                <i class="fa-regular fa-folder-open text-5xl text-slate-600"></i>
                <h3 class="text-lg font-bold text-slate-300">Aucun livre dans votre bibliothèque locale</h3>
                <p class="text-sm text-slate-400">Recherchez un ouvrage dans l'onglet "Rechercher" ou importez un fichier local pour commencer.</p>
            </div>
        </section>

    </main>

    <!-- READER MODAL -->
    <div id="reader-modal" class="fixed inset-0 z-50 bg-slate-950/90 backdrop-blur-md hidden flex flex-col">
        <!-- Reader Toolbar -->
        <header class="bg-slate-900/95 border-b border-slate-800 px-6 py-3 flex items-center justify-between shadow-xl">
            <div class="flex items-center space-x-3">
                <button onclick="closeReader()" class="w-9 h-9 rounded-xl bg-slate-800 hover:bg-slate-700 text-slate-300 hover:text-white flex items-center justify-center transition">
                    <i class="fa-solid fa-xmark"></i>
                </button>
                <div class="truncate max-w-md">
                    <h2 id="reader-title" class="font-bold text-sm text-white truncate">Titre de l'œuvre</h2>
                    <p id="reader-author" class="text-xs text-slate-400 truncate">Auteur</p>
                </div>
            </div>

            <div class="flex items-center space-x-3">
                <!-- Chapter Selector -->
                <select id="reader-toc" onchange="selectChapter(this.value)" class="bg-slate-950 border border-slate-700 text-xs text-slate-200 rounded-xl px-3 py-1.5 focus:outline-none focus:border-amber-400 max-w-[200px] truncate"></select>

                <!-- Translate Chapter Button -->
                <button onclick="translateCurrentChapter()" id="btn-translate-chap" class="px-3 py-1.5 bg-indigo-600/30 hover:bg-indigo-600/50 text-indigo-200 border border-indigo-500/40 rounded-xl text-xs font-semibold transition flex items-center space-x-1.5">
                    <i class="fa-solid fa-language text-amber-400"></i>
                    <span>Traduire ce chapitre</span>
                </button>

                <!-- Font Family -->
                <select id="reader-font" onchange="changeReaderFont(this.value)" class="bg-slate-950 border border-slate-700 text-xs text-slate-200 rounded-xl px-2 py-1.5">
                    <option value="font-merriweather">Serif (Merriweather)</option>
                    <option value="font-inter">Sans (Inter)</option>
                    <option value="font-mono-reading">Mono (JetBrains)</option>
                </select>

                <!-- Font Size Controls -->
                <div class="flex items-center bg-slate-950 border border-slate-700 rounded-xl px-1.5 py-0.5">
                    <button onclick="adjustFontSize(-1)" class="w-7 h-7 text-xs text-slate-300 hover:text-white flex items-center justify-center"><i class="fa-solid fa-minus"></i></button>
                    <span id="font-size-label" class="text-xs font-mono px-2 text-slate-400">18px</span>
                    <button onclick="adjustFontSize(1)" class="w-7 h-7 text-xs text-slate-300 hover:text-white flex items-center justify-center"><i class="fa-solid fa-plus"></i></button>
                </div>

                <!-- Theme Controls -->
                <div class="flex items-center bg-slate-950 border border-slate-700 rounded-xl p-0.5">
                    <button onclick="setReaderTheme('dark')" id="theme-btn-dark" class="w-7 h-7 rounded-lg text-xs bg-slate-800 text-amber-300 flex items-center justify-center"><i class="fa-solid fa-moon"></i></button>
                    <button onclick="setReaderTheme('sepia')" id="theme-btn-sepia" class="w-7 h-7 rounded-lg text-xs text-amber-700 hover:bg-amber-100/10 flex items-center justify-center font-bold">S</button>
                    <button onclick="setReaderTheme('light')" id="theme-btn-light" class="w-7 h-7 rounded-lg text-xs text-slate-400 hover:bg-white/10 flex items-center justify-center"><i class="fa-solid fa-sun"></i></button>
                </div>
            </div>
        </header>

        <!-- Reader Scroll Content -->
        <div id="reader-scroll-container" class="flex-1 overflow-y-auto custom-scroll p-6 flex justify-center reader-dark">
            <div id="reader-body" class="max-w-3xl w-full py-8 font-merriweather text-[18px] leading-relaxed transition-all">
                <!-- Chapter Content will be injected here -->
            </div>
        </div>

        <!-- Reader Footer / Navigation -->
        <footer class="bg-slate-900/90 border-t border-slate-800 px-6 py-2.5 flex items-center justify-between text-xs text-slate-400">
            <button onclick="prevChapter()" id="btn-prev-chap" class="hover:text-white flex items-center space-x-1.5 transition">
                <i class="fa-solid fa-chevron-left"></i>
                <span>Chapitre précédent</span>
            </button>
            <span id="reader-progress" class="font-mono">Chapitre 1 / 1</span>
            <button onclick="nextChapter()" id="btn-next-chap" class="hover:text-white flex items-center space-x-1.5 transition">
                <span>Chapitre suivant</span>
                <i class="fa-solid fa-chevron-right"></i>
            </button>
        </footer>
    </div>

    <!-- GENERATE / DOWNLOAD / TRANSLATE MODAL -->
    <div id="generate-modal" class="fixed inset-0 z-50 bg-slate-950/80 backdrop-blur-sm hidden flex items-center justify-center p-4">
        <div class="bg-slate-900 border border-slate-800 w-full max-w-lg rounded-3xl p-6 shadow-2xl space-y-6 relative">
            <button onclick="closeGenerateModal()" class="absolute right-5 top-5 w-8 h-8 rounded-full bg-slate-800 text-slate-400 hover:text-white flex items-center justify-center">
                <i class="fa-solid fa-xmark"></i>
            </button>

            <div>
                <h3 class="text-lg font-bold text-white flex items-center">
                    <i class="fa-solid fa-wand-magic-sparkles text-amber-400 mr-2"></i>Générateur d'Édition
                </h3>
                <p id="modal-book-title" class="text-xs text-slate-400 mt-1 truncate">Titre de l'œuvre</p>
            </div>

            <div class="space-y-4">
                <!-- Format Option -->
                <div class="space-y-2">
                    <label class="text-xs font-semibold text-slate-300">Format de sortie :</label>
                    <div class="grid grid-cols-2 gap-2">
                        <label class="flex items-center space-x-2.5 p-3 rounded-xl border border-slate-800 bg-slate-950/60 cursor-pointer hover:border-amber-500/40">
                            <input type="radio" name="modal-fmt" value="epub" checked class="text-amber-500 focus:ring-amber-400">
                            <div>
                                <p class="text-xs font-bold text-white">EPUB Standard</p>
                                <p class="text-[10px] text-slate-400">Kobo, Apple Books, Calibre</p>
                            </div>
                        </label>
                        <label class="flex items-center space-x-2.5 p-3 rounded-xl border border-slate-800 bg-slate-950/60 cursor-pointer hover:border-amber-500/40">
                            <input type="radio" name="modal-fmt" value="kindle_epub" class="text-amber-500 focus:ring-amber-400">
                            <div>
                                <p class="text-xs font-bold text-white">EPUB Kindle</p>
                                <p class="text-[10px] text-slate-400">Send to Kindle Amazon</p>
                            </div>
                        </label>
                        <label class="flex items-center space-x-2.5 p-3 rounded-xl border border-slate-800 bg-slate-950/60 cursor-pointer hover:border-amber-500/40">
                            <input type="radio" name="modal-fmt" value="pdf_ereader" class="text-amber-500 focus:ring-amber-400">
                            <div>
                                <p class="text-xs font-bold text-white">PDF Liseuse (6")</p>
                                <p class="text-[10px] text-slate-400">Kindle Paperwhite, Kobo Clara</p>
                            </div>
                        </label>
                        <label class="flex items-center space-x-2.5 p-3 rounded-xl border border-slate-800 bg-slate-950/60 cursor-pointer hover:border-amber-500/40">
                            <input type="radio" name="modal-fmt" value="pdf_a4" class="text-amber-500 focus:ring-amber-400">
                            <div>
                                <p class="text-xs font-bold text-white">PDF Format A4</p>
                                <p class="text-[10px] text-slate-400">Impression / PC / Tablette</p>
                            </div>
                        </label>
                        <label class="flex items-center space-x-2.5 p-3 rounded-xl border border-slate-800 bg-slate-950/60 cursor-pointer hover:border-amber-500/40">
                            <input type="radio" name="modal-fmt" value="txt" class="text-amber-500 focus:ring-amber-400">
                            <div>
                                <p class="text-xs font-bold text-white">Texte Brut (.txt)</p>
                                <p class="text-[10px] text-slate-400">UTF-8 épuré</p>
                            </div>
                        </label>
                        <label class="flex items-center space-x-2.5 p-3 rounded-xl border border-slate-800 bg-slate-950/60 cursor-pointer hover:border-amber-500/40">
                            <input type="radio" name="modal-fmt" value="html" class="text-amber-500 focus:ring-amber-400">
                            <div>
                                <p class="text-xs font-bold text-white">Document HTML</p>
                                <p class="text-[10px] text-slate-400">Hors-ligne dans navigateur</p>
                            </div>
                        </label>
                    </div>
                </div>

                <!-- Language Option -->
                <div class="space-y-2">
                    <label class="text-xs font-semibold text-slate-300">Traduction :</label>
                    <select id="modal-lang" class="w-full bg-slate-950 border border-slate-700 rounded-xl px-3 py-2 text-xs text-white focus:outline-none focus:border-amber-400">
                        <option value="none">Conserver la langue d'origine (Édition Propre)</option>
                        <option value="fr">Traduire en Français (FR)</option>
                        <option value="en">Traduire en Anglais (EN)</option>
                        <option value="es">Traduire en Espagnol (ES)</option>
                        <option value="de">Traduire en Allemand (DE)</option>
                        <option value="it">Traduire en Italien (IT)</option>
                        <option value="ru">Traduire en Russe (RU)</option>
                        <option value="pt">Traduire en Portugais (PT)</option>
                    </select>
                </div>
            </div>

            <!-- Action buttons -->
            <div class="flex items-center justify-end space-x-3 pt-2">
                <button onclick="closeGenerateModal()" class="px-4 py-2 rounded-xl text-xs font-semibold text-slate-400 hover:text-white transition">Annuler</button>
                <button onclick="startGenerationJob()" class="px-6 py-2.5 bg-gradient-to-r from-amber-500 to-amber-600 hover:from-amber-400 hover:to-amber-500 text-slate-950 font-bold rounded-xl text-xs shadow-lg shadow-amber-500/20 transition">
                    Générer le livre
                </button>
            </div>
        </div>
    </div>

    <!-- PROGRESS TOAST -->
    <div id="progress-toast" class="fixed bottom-6 right-6 z-50 bg-slate-900 border border-slate-700 shadow-2xl rounded-2xl p-4 w-80 hidden space-y-3">
        <div class="flex items-center justify-between">
            <span id="toast-title" class="text-xs font-bold text-white flex items-center">
                <i class="fa-solid fa-circle-notch animate-spin text-amber-400 mr-2"></i>Génération en cours...
            </span>
            <span id="toast-pct" class="text-xs font-mono text-amber-400 font-semibold">0%</span>
        </div>
        <div class="w-full bg-slate-950 rounded-full h-2 overflow-hidden border border-slate-800">
            <div id="toast-bar" class="bg-amber-400 h-full transition-all duration-300" style="width: 0%"></div>
        </div>
        <p id="toast-msg" class="text-[11px] text-slate-400 truncate">Initialisation...</p>
    </div>

    <script>
        // State
        let currentChapters = [];
        let currentChapterIndex = 0;
        let activeModalBookId = null;
        let readerFontSize = parseInt(localStorage.getItem('readerFontSize') || '18');
        let currentFilter = 'all';
        let allLibraryBooks = [];

        // Apply saved theme
        const savedTheme = localStorage.getItem('readerTheme') || 'dark';

        function switchTab(tab) {
            const tabSearch = document.getElementById('tab-search');
            const tabLib = document.getElementById('tab-library');
            const btnSearch = document.getElementById('tab-btn-search');
            const btnLib = document.getElementById('tab-btn-library');

            if (tab === 'search') {
                tabSearch.classList.remove('hidden');
                tabLib.classList.add('hidden');
                btnSearch.className = "px-4 py-2 rounded-xl text-sm font-semibold transition-all bg-indigo-600/30 text-amber-300 border border-indigo-500/50 shadow-inner";
                btnLib.className = "px-4 py-2 rounded-xl text-sm font-semibold transition-all text-slate-300 hover:bg-slate-800 border border-transparent";
            } else {
                tabSearch.classList.add('hidden');
                tabLib.classList.remove('hidden');
                btnLib.className = "px-4 py-2 rounded-xl text-sm font-semibold transition-all bg-indigo-600/30 text-amber-300 border border-indigo-500/50 shadow-inner";
                btnSearch.className = "px-4 py-2 rounded-xl text-sm font-semibold transition-all text-slate-300 hover:bg-slate-800 border border-transparent";
                loadLibrary();
            }
        }

        async function handleSearch(e) {
            e.preventDefault();
            const q = document.getElementById('search-input').value.trim();
            if (!q) return;

            const lang = document.getElementById('filter-lang').value;
            const source = document.getElementById('filter-source').value;

            document.getElementById('search-empty').classList.add('hidden');
            document.getElementById('results-grid').innerHTML = '';
            document.getElementById('results-count').innerText = '';
            document.getElementById('search-loading').classList.remove('hidden');

            try {
                const resp = await fetch(`/api/search?q=${encodeURIComponent(q)}&lang=${lang}&source=${source}`);
                const data = await resp.json();
                renderResults(data.results || []);
            } catch (err) {
                alert("Erreur lors de la recherche : " + err.message);
            } finally {
                document.getElementById('search-loading').classList.add('hidden');
            }
        }

        function quickSearch(term) {
            document.getElementById('search-input').value = term;
            document.getElementById('search-form').dispatchEvent(new Event('submit'));
        }

        function renderResults(books) {
            const grid = document.getElementById('results-grid');
            const countEl = document.getElementById('results-count');
            grid.innerHTML = '';

            if (books.length === 0) {
                countEl.innerText = "Aucun résultat trouvé pour ces critères.";
                return;
            }

            countEl.innerText = `${books.length} œuvres trouvées dans le domaine public :`;

            books.forEach(b => {
                const card = document.createElement('div');
                card.className = "bg-slate-900/80 hover:bg-slate-900 border border-slate-800 hover:border-amber-500/40 rounded-3xl p-5 shadow-xl transition-all duration-300 flex flex-col justify-between group";

                const coverImg = b.cover_url 
                    ? `<img src="${b.cover_url}" alt="${b.title}" class="w-16 h-24 object-cover rounded-xl shadow-md border border-slate-800 flex-shrink-0 group-hover:scale-105 transition-transform">`
                    : `<div class="w-16 h-24 bg-slate-800 rounded-xl border border-slate-700 flex items-center justify-center text-slate-500 flex-shrink-0"><i class="fa-solid fa-book text-xl"></i></div>`;

                card.innerHTML = `
                    <div class="flex space-x-4">
                        ${coverImg}
                        <div class="flex-1 min-w-0">
                            <div class="flex items-center space-x-2">
                                <span class="text-[10px] bg-indigo-500/20 text-indigo-300 border border-indigo-500/30 px-2 py-0.5 rounded-md font-semibold uppercase">${b.source}</span>
                                <span class="text-[10px] bg-slate-800 text-slate-400 px-2 py-0.5 rounded-md font-mono">${b.language.toUpperCase()}</span>
                            </div>
                            <h3 class="font-bold text-white text-base mt-2 line-clamp-2 leading-snug group-hover:text-amber-200 transition" title="${b.title}">${b.title}</h3>
                            <p class="text-xs text-slate-400 mt-1 truncate"><i class="fa-solid fa-feather-pointed mr-1 text-slate-500"></i>${b.author}</p>
                            ${b.downloads ? `<p class="text-[11px] text-amber-400/80 mt-1 font-mono"><i class="fa-solid fa-chart-simple mr-1"></i>${b.downloads} lectures</p>` : ''}
                        </div>
                    </div>

                    <div class="mt-4 pt-3 border-t border-slate-800/80 flex items-center justify-between gap-2">
                        <button onclick="openPreviewReader('${escapeQuotes(b.id)}')" class="px-3.5 py-2 bg-slate-800 hover:bg-slate-700 text-slate-200 rounded-xl text-xs font-semibold transition flex items-center">
                            <i class="fa-solid fa-book-open-reader mr-1.5 text-amber-400"></i>Lire
                        </button>

                        <button onclick="openGenerateModal('${escapeQuotes(b.id)}', '${escapeQuotes(b.title)}')" class="px-4 py-2 bg-gradient-to-r from-amber-500 to-amber-600 hover:from-amber-400 hover:to-amber-500 text-slate-950 font-bold rounded-xl text-xs shadow-lg shadow-amber-500/20 transition flex items-center">
                            <i class="fa-solid fa-wand-magic-sparkles mr-1.5"></i>Générer / Télécharger
                        </button>
                    </div>
                `;
                grid.appendChild(card);
            });
        }

        function escapeQuotes(str) {
            return (str || '').replace(/'/g, "\\'").replace(/"/g, '&quot;');
        }

        // Reader functions
        async function openPreviewReader(bookId) {
            showToast("Chargement de l'œuvre...", 30);
            try {
                const resp = await fetch(`/api/preview?book_id=${encodeURIComponent(bookId)}`);
                if (!resp.ok) throw new Error("Impossible de charger la prévisualisation");
                const data = await resp.json();
                launchReader(data.title, data.author, data.chapters);
            } catch (err) {
                alert("Erreur de prévisualisation : " + err.message);
            } finally {
                hideToast();
            }
        }

        async function openLocalBookInReader(filename) {
            showToast("Ouverture du livre local...", 40);
            try {
                const resp = await fetch(`/api/read-local/${encodeURIComponent(filename)}`);
                if (!resp.ok) throw new Error("Impossible d'ouvrir ce livre localement");
                const data = await resp.json();
                launchReader(data.title, data.author, data.chapters);
            } catch (err) {
                alert("Erreur de lecture : " + err.message);
            } finally {
                hideToast();
            }
        }

        function launchReader(title, author, chapters) {
            currentChapters = chapters || [];
            currentChapterIndex = 0;

            document.getElementById('reader-title').innerText = title || "Sans titre";
            document.getElementById('reader-author').innerText = author || "Auteur inconnu";

            const tocEl = document.getElementById('reader-toc');
            tocEl.innerHTML = '';
            currentChapters.forEach((c, idx) => {
                const opt = document.createElement('option');
                opt.value = idx;
                opt.innerText = c.title || `Chapitre ${idx + 1}`;
                tocEl.appendChild(opt);
            });

            setReaderTheme(savedTheme);
            adjustFontSize(0);
            renderCurrentChapter();

            document.getElementById('reader-modal').classList.remove('hidden');
        }

        function renderCurrentChapter() {
            if (!currentChapters.length) {
                document.getElementById('reader-body').innerHTML = '<p class="text-center py-20 text-slate-500">Aucun contenu trouvé.</p>';
                return;
            }

            const chap = currentChapters[currentChapterIndex];
            document.getElementById('reader-toc').value = currentChapterIndex;
            document.getElementById('reader-progress').innerText = `Chapitre ${currentChapterIndex + 1} / ${currentChapters.length}`;
            document.getElementById('reader-body').innerHTML = chap.html || `<p>${chap.text || ''}</p>`;
            document.getElementById('reader-scroll-container').scrollTop = 0;

            document.getElementById('btn-prev-chap').disabled = currentChapterIndex === 0;
            document.getElementById('btn-next-chap').disabled = currentChapterIndex === currentChapters.length - 1;
        }

        function selectChapter(idx) {
            currentChapterIndex = parseInt(idx);
            renderCurrentChapter();
        }

        function prevChapter() {
            if (currentChapterIndex > 0) {
                currentChapterIndex--;
                renderCurrentChapter();
            }
        }

        function nextChapter() {
            if (currentChapterIndex < currentChapters.length - 1) {
                currentChapterIndex++;
                renderCurrentChapter();
            }
        }

        function closeReader() {
            document.getElementById('reader-modal').classList.add('hidden');
        }

        function setReaderTheme(theme) {
            const container = document.getElementById('reader-scroll-container');
            container.className = "flex-1 overflow-y-auto custom-scroll p-6 flex justify-center " + (
                theme === 'dark' ? 'reader-dark' : (theme === 'sepia' ? 'reader-sepia' : 'reader-light')
            );
            localStorage.setItem('readerTheme', theme);
        }

        function adjustFontSize(delta) {
            readerFontSize = Math.max(14, Math.min(32, readerFontSize + delta));
            document.getElementById('reader-body').style.fontSize = `${readerFontSize}px`;
            document.getElementById('font-size-label').innerText = `${readerFontSize}px`;
            localStorage.setItem('readerFontSize', readerFontSize);
        }

        function changeReaderFont(fontClass) {
            const bodyEl = document.getElementById('reader-body');
            bodyEl.classList.remove('font-merriweather', 'font-inter', 'font-mono-reading');
            bodyEl.classList.add(fontClass);
        }

        async function translateCurrentChapter() {
            const btn = document.getElementById('btn-translate-chap');
            const originalHTML = btn.innerHTML;
            btn.innerHTML = '<i class="fa-solid fa-circle-notch animate-spin mr-1"></i> Traduction...';
            btn.disabled = true;

            try {
                const chap = currentChapters[currentChapterIndex];
                const resp = await fetch('/api/translate-chapter', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ html: chap.html, target_lang: 'fr' })
                });
                const data = await resp.json();
                if (data.translated_html) {
                    chap.html = data.translated_html;
                    renderCurrentChapter();
                }
            } catch (err) {
                alert("Erreur de traduction : " + err.message);
            } finally {
                btn.innerHTML = originalHTML;
                btn.disabled = false;
            }
        }

        // Generate Modal
        function openGenerateModal(bookId, bookTitle) {
            activeModalBookId = bookId;
            document.getElementById('modal-book-title').innerText = bookTitle || bookId;
            document.getElementById('generate-modal').classList.remove('hidden');
        }

        function closeGenerateModal() {
            document.getElementById('generate-modal').classList.add('hidden');
        }

        async function startGenerationJob() {
            const fmt = document.querySelector('input[name="modal-fmt"]:checked').value;
            const lang = document.getElementById('modal-lang').value;

            closeGenerateModal();
            showToast("Démarrage du téléchargement...", 10);

            try {
                const resp = await fetch(`/api/generate?book_id=${encodeURIComponent(activeModalBookId)}&format=${fmt}&target_lang=${lang === 'none' ? '' : lang}`, { method: 'POST' });
                const data = await resp.json();
                pollJobProgress(data.job_id);
            } catch (err) {
                alert("Erreur lors de la génération : " + err.message);
                hideToast();
            }
        }

        function pollJobProgress(jobId) {
            const timer = setInterval(async () => {
                try {
                    const resp = await fetch(`/api/job/${jobId}`);
                    const job = await resp.json();

                    showToast(job.message, job.percent);

                    if (job.status === 'done') {
                        clearInterval(timer);
                        showToast(job.message, 100);
                        setTimeout(() => {
                            hideToast();
                            switchTab('library');
                        }, 2000);
                    } else if (job.status === 'error') {
                        clearInterval(timer);
                        alert("Échec de la tâche : " + job.message);
                        hideToast();
                    }
                } catch (e) {
                    clearInterval(timer);
                    hideToast();
                }
            }, 1000);
        }

        function showToast(msg, pct) {
            const toast = document.getElementById('progress-toast');
            toast.classList.remove('hidden');
            document.getElementById('toast-msg').innerText = msg;
            document.getElementById('toast-pct').innerText = `${pct}%`;
            document.getElementById('toast-bar').style.width = `${pct}%`;
        }

        function hideToast() {
            document.getElementById('progress-toast').classList.add('hidden');
        }

        // Library Management
        async function loadLibrary() {
            try {
                const resp = await fetch('/api/library');
                const data = await resp.json();
                allLibraryBooks = data.books || [];
                document.getElementById('library-count').innerText = allLibraryBooks.length;
                renderLibrary();
            } catch (e) {
                console.error("Library load error", e);
            }
        }

        function filterLibrary(fmt) {
            currentFilter = fmt;
            document.querySelectorAll('.lib-filter-btn').forEach(b => {
                if (b.getAttribute('data-filter') === fmt) {
                    b.className = "lib-filter-btn px-3 py-1.5 rounded-xl text-xs font-semibold bg-amber-500/20 text-amber-300 border border-amber-500/40";
                } else {
                    b.className = "lib-filter-btn px-3 py-1.5 rounded-xl text-xs font-medium text-slate-400 hover:text-white";
                }
            });
            renderLibrary();
        }

        function renderLibrary() {
            const grid = document.getElementById('library-grid');
            const emptyEl = document.getElementById('library-empty');
            grid.innerHTML = '';

            const filtered = currentFilter === 'all' 
                ? allLibraryBooks 
                : allLibraryBooks.filter(b => b.format.includes(currentFilter));

            if (filtered.length === 0) {
                emptyEl.classList.remove('hidden');
                return;
            } else {
                emptyEl.classList.add('hidden');
            }

            filtered.forEach(b => {
                const card = document.createElement('div');
                card.className = "bg-slate-900/80 border border-slate-800 hover:border-amber-500/40 rounded-3xl p-5 shadow-xl transition-all duration-300 flex flex-col justify-between group";

                let fmtBadgeColor = 'bg-emerald-500/20 text-emerald-300 border-emerald-500/40';
                if (b.format.includes('PDF')) fmtBadgeColor = 'bg-rose-500/20 text-rose-300 border-rose-500/40';
                else if (b.format === 'TXT') fmtBadgeColor = 'bg-blue-500/20 text-blue-300 border-blue-500/40';
                else if (b.format === 'HTML') fmtBadgeColor = 'bg-purple-500/20 text-purple-300 border-purple-500/40';

                const transBadge = b.is_translated 
                    ? '<span class="text-[10px] bg-amber-500/20 text-amber-300 border border-amber-500/40 px-2 py-0.5 rounded-md font-bold uppercase mr-1.5"><i class="fa-solid fa-language mr-1"></i>Traduit</span>' 
                    : '';

                let coverSnippet = '';
                if (b.has_cover && b.cover_url) {
                    coverSnippet = `<img src="${b.cover_url}" alt="Cover" class="w-14 h-20 object-cover rounded-lg border border-slate-700 shadow flex-shrink-0">`;
                } else {
                    coverSnippet = `<div class="w-14 h-20 bg-slate-800/80 rounded-lg border border-slate-700 flex flex-col items-center justify-center text-slate-500 flex-shrink-0">
                        <i class="fa-solid fa-book-bookmark text-lg text-amber-400/60"></i>
                        <span class="text-[9px] font-mono mt-1">${b.format}</span>
                    </div>`;
                }

                let readButton = '';
                if (b.format === 'EPUB' || b.format === 'KINDLE EPUB') {
                    readButton = `<button onclick="openLocalBookInReader('${escapeQuotes(b.filename)}')" class="px-3.5 py-2 bg-indigo-600/25 hover:bg-indigo-600/40 text-indigo-300 border border-indigo-500/40 rounded-xl text-xs font-bold transition flex items-center">
                        <i class="fa-solid fa-book-open-reader mr-1.5"></i>Lire
                    </button>`;
                } else {
                    readButton = `<a href="/api/download/${encodeURIComponent(b.filename)}" target="_blank" class="px-3.5 py-2 bg-indigo-600/25 hover:bg-indigo-600/40 text-indigo-300 border border-indigo-500/40 rounded-xl text-xs font-bold transition flex items-center">
                        <i class="fa-solid fa-arrow-up-right-from-square mr-1.5"></i>Ouvrir
                    </a>`;
                }

                card.innerHTML = `
                    <div>
                        <div class="flex items-center justify-between">
                            <div class="flex items-center">
                                ${transBadge}
                                <span class="text-[10px] px-2 py-0.5 rounded-md font-bold uppercase border ${fmtBadgeColor}">${b.format}</span>
                            </div>
                            <span class="text-xs text-slate-400 font-mono">${b.size}</span>
                        </div>
                        
                        <div class="flex space-x-3 mt-3">
                            ${coverSnippet}
                            <div class="flex-1 min-w-0">
                                <h3 class="font-bold text-white text-base line-clamp-2 cursor-pointer hover:text-amber-200 transition" onclick="${b.format.includes('EPUB') ? `openLocalBookInReader('${escapeQuotes(b.filename)}')` : `window.open('/api/download/${encodeURIComponent(b.filename)}')`}" title="${b.title}">${b.title}</h3>
                                <p class="text-xs text-slate-400 mt-1 truncate"><i class="fa-solid fa-feather-pointed mr-1 text-slate-500"></i>${b.author}</p>
                                <p class="text-[11px] text-slate-500 mt-1 font-mono truncate" title="${b.filename}">${b.filename}</p>
                            </div>
                        </div>
                    </div>

                    <div class="mt-4 pt-3 border-t border-slate-800 flex items-center justify-between gap-2">
                        ${readButton}

                        <div class="flex items-center space-x-1.5">
                            <a href="/api/download/${encodeURIComponent(b.filename)}" download="${b.filename}" class="px-3 py-2 bg-gradient-to-r from-amber-500 to-amber-600 hover:from-amber-400 hover:to-amber-500 text-slate-950 font-bold rounded-xl text-xs flex items-center shadow-lg shadow-amber-500/20" title="Télécharger le fichier">
                                <i class="fa-solid fa-download"></i>
                            </a>
                            <button onclick="confirmDeleteBook('${escapeQuotes(b.filename)}')" class="px-2.5 py-2 bg-rose-500/20 hover:bg-rose-500/30 text-rose-300 border border-rose-500/30 rounded-xl text-xs transition" title="Supprimer ce livre de la bibliothèque">
                                <i class="fa-regular fa-trash-can"></i>
                            </button>
                        </div>
                    </div>
                `;
                grid.appendChild(card);
            });
        }

        async function confirmDeleteBook(filename) {
            if (!confirm(`Voulez-vous vraiment supprimer définitivement "${filename}" de votre bibliothèque ?`)) {
                return;
            }
            try {
                const resp = await fetch(`/api/book/${encodeURIComponent(filename)}`, { method: 'DELETE' });
                if (resp.ok) {
                    loadLibrary();
                } else {
                    alert("Impossible de supprimer le livre.");
                }
            } catch (err) {
                alert("Erreur lors de la suppression : " + err.message);
            }
        }

        async function handleFileUpload(event) {
            const file = event.target.files[0];
            if (!file) return;

            const formData = new FormData();
            formData.append('file', file);

            showToast(`Importation de "${file.name}"...`, 50);

            try {
                const resp = await fetch('/api/upload', {
                    method: 'POST',
                    body: formData
                });
                if (!resp.ok) throw new Error("Erreur de téléversement");
                showToast("Fichier importé avec succès !", 100);
                setTimeout(() => {
                    hideToast();
                    switchTab('library');
                }, 1500);
            } catch (err) {
                alert("Erreur lors de l'importation : " + err.message);
                hideToast();
            } finally {
                event.target.value = '';
            }
        }

        async function openEpubsFolder() {
            try {
                await fetch('/api/open-folder', { method: 'POST' });
            } catch (e) {
                alert("Erreur : " + e.message);
            }
        }

        // Initialize library
        loadLibrary();
    </script>
</body>
</html>"""

def main():
    uvicorn.run("web_app:app", host="127.0.0.1", port=8000, reload=False)

if __name__ == "__main__":
    main()
