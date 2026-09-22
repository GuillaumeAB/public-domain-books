import os
import sys
import argparse
import webbrowser
import uvicorn

# Ensure UTF-8 output on Windows console
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from search_engine import search_books, LANG_NAMES
from downloader import download_book
from epub_cleaner import clean_epub
from epub_builder import build_epub_from_text
from translator import translate_epub
from format_exporter import convert_epub_to_format
from library_manager import list_library_epubs, open_epubs_folder, delete_library_book, EPUBS_DIR

def cmd_delete(args):
    filename = args.filename
    print(f"\n🗑️ Suppression de : '{filename}'...")
    if delete_library_book(filename):
        print(f"✅ Livre '{filename}' supprimé avec succès.")
    else:
        print(f"❌ Impossible de supprimer '{filename}'. Vérifiez le nom du fichier.")


def cmd_search(args):
    print(f"\n🔍 Recherche de : '{args.query}' (langue: {args.lang or 'toutes'}, source: {args.source})...\n")
    results = search_books(args.query, lang=args.lang, source=args.source, max_results=args.limit)
    if not results:
        print("❌ Aucun livre trouvé.")
        return

    print(f"✅ {len(results)} livres trouvés :\n")
    for i, b in enumerate(results, 1):
        print(f"[{i}] {b['title']}")
        print(f"    Auteur : {b['author']} | Langue : {b['language']} | Source : {b['source']}")
        print(f"    ID     : {b['id']}")
        if b.get('downloads'):
            print(f"    Téléchargements : {b['downloads']}")
        print("-" * 60)
    print("\n💡 Pour générer une version propre d'un livre :")
    print(f"   python pd_epub.py get \"{results[0]['id']}\" --clean")
    print("💡 Pour traduire et générer l'EPUB dans une autre langue :")
    print(f"   python pd_epub.py get \"{results[0]['id']}\" --translate fr\n")

def cmd_get(args):
    book_id = args.book_id
    print(f"\n📥 Téléchargement de l'œuvre '{book_id}'...")
    dl_path, fmt, meta = download_book(book_id)
    if not dl_path or not os.path.exists(dl_path):
        print(f"❌ Erreur : Impossible de télécharger '{book_id}'.")
        return

    print(f"✨ Format détecté : {fmt.upper()}")
    print(f"📖 Titre : {meta.get('title')}")
    print(f"✍️  Auteur : {meta.get('author')}")

    print("\n🧹 Nettoyage typographique & création de l'EPUB Propre...")
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

    if not clean_path or not os.path.exists(clean_path):
        print("❌ Erreur lors de la génération de l'EPUB.")
        return

    print(f"✅ EPUB Propre généré : {clean_path}")

    final_file = None
    if args.translate:
        target_lang = args.translate.lower()
        print(f"\n🌍 Traduction intégrale en cours vers '{target_lang.upper()}'...")
        def progress(pct, msg):
            sys.stdout.write(f"\r   [{pct}%] {msg:<60}")
            sys.stdout.flush()

        trans_path = translate_epub(
            input_epub_path=clean_path,
            output_dir=EPUBS_DIR,
            target_lang=target_lang,
            progress_callback=progress
        )
        final_file = trans_path
    else:
        final_file = clean_path

    # Format export if requested
    fmt_target = getattr(args, "format", "epub")
    if fmt_target and fmt_target not in ("epub", "kindle"):
        print(f"\n📑 Conversion vers le format '{fmt_target.upper()}'...")
        final_file = convert_epub_to_format(final_file, fmt_target, EPUBS_DIR)

    print(f"\n🎉 Livre généré avec succès ({fmt_target.upper()}) :")
    print(f"   📁 {final_file}\n")

def cmd_list(args):
    books = list_library_epubs()
    print(f"\n📚 Vos documents disponibles ({len(books)}) dans '{EPUBS_DIR}' :\n")
    if not books:
        print("   (Aucun livre pour l'instant. Utilisez 'search' ou 'serve')")
        return
    for i, b in enumerate(books, 1):
        type_str = "TRADUIT" if b["is_translated"] else "ÉDITION PROPRE"
        print(f"[{i}] {b['title']} [{b.get('format', 'EPUB')}] [{type_str}]")
        print(f"    Auteur : {b['author']} | Taille : {b['size']}")
        print(f"    Fichier: {b['filename']}")
        print("-" * 60)

def cmd_serve(args):
    host = args.host
    port = args.port
    url = f"http://{host}:{port}"
    print("\n" + "=" * 65)
    print(" 🚀 LANCEMENT DU SERVEUR BIBLIOTHÈQUE LIBRE & MULTI-FORMATS")
    print(f" 🌐 Interface Web accessible à l'adresse : {url}")
    print("=" * 65 + "\n")

    if not args.no_open:
        threading_timer = webbrowser.open(url)

    from web_app import app
    uvicorn.run(app, host=host, port=port)

def main():
    parser = argparse.ArgumentParser(description="Outil de recherche de livres du domaine public, génération multi-formats (EPUB, Kindle, PDF, TXT, HTML) et traduction.")
    subparsers = parser.add_subparsers(dest="command", help="Commandes disponibles")

    # Serve command (Web UI)
    p_serve = subparsers.add_parser("serve", help="Lancer l'interface Web interactive dans votre navigateur")
    p_serve.add_argument("--host", default="127.0.0.1", help="Hôte d'écoute (défaut: 127.0.0.1)")
    p_serve.add_argument("--port", type=int, default=8000, help="Port d'écoute (défaut: 8000)")
    p_serve.add_argument("--no-open", action="store_true", help="Ne pas ouvrir automatiquement le navigateur")

    # Search command
    p_search = subparsers.add_parser("search", help="Rechercher des livres dans le domaine public")
    p_search.add_argument("query", help="Titre, auteur ou mots-clés")
    p_search.add_argument("--lang", default=None, help="Filtrer par langue (ex: fr, en, de, es, it, la, etc.)")
    p_search.add_argument("--source", default="all", choices=["all", "gutenberg", "ia", "wikisource", "standard_ebooks"], help="Source du catalogue")
    p_search.add_argument("--limit", type=int, default=15, help="Nombre max de résultats")

    # Get / Download / Clean / Translate command
    p_get = subparsers.add_parser("get", help="Télécharger un livre, le nettoyer en EPUB ou le traduire")
    p_get.add_argument("book_id", help="Identifiant du livre (ex: gutenberg:6099 ou ia:identifier ou wikisource:fr:Titre)")
    p_get.add_argument("--clean", action="store_true", help="Nettoyer et générer l'EPUB")
    p_get.add_argument("--translate", default=None, help="Langue cible de traduction (ex: fr, en, es, de, it, ru, etc.)")
    p_get.add_argument("--format", default="epub", choices=["epub", "kindle", "pdf_ereader", "pdf_a4", "txt", "html"], help="Format de sortie (défaut: epub)")

    # List command
    p_list = subparsers.add_parser("list", help="Lister tous les EPUBs déjà générés")

    # Delete command
    p_delete = subparsers.add_parser("delete", help="Supprimer un livre de votre bibliothèque locale")
    p_delete.add_argument("filename", help="Nom du fichier à supprimer (ex: MonLivre.epub)")

    # Folder command
    p_folder = subparsers.add_parser("folder", help="Ouvrir le dossier des EPUBs dans l'Explorateur Windows")

    args = parser.parse_args()

    if args.command == "serve":
        cmd_serve(args)
    elif args.command == "search":
        cmd_search(args)
    elif args.command == "get":
        cmd_get(args)
    elif args.command == "list":
        cmd_list(args)
    elif args.command == "delete":
        cmd_delete(args)
    elif args.command == "folder":
        open_epubs_folder()
        print(f"Dossier ouvert : {EPUBS_DIR}")
    else:
        # If no arguments provided, default to serve!
        cmd_serve(argparse.Namespace(host="127.0.0.1", port=8000, no_open=False))

if __name__ == "__main__":
    main()
