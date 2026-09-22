import os
import re
from typing import List, Dict, Any, Optional
from bs4 import BeautifulSoup
from fpdf import FPDF
import ebooklib
from ebooklib import epub
from epub_cleaner import sanitize_filename, CLEAN_CSS

def clean_unicode_for_pdf(text: str) -> str:
    """Normalizes complex unicode characters to ensure 100% crash-free PDF rendering."""
    if not text:
        return ""
    replacements = {
        '’': "'",
        '‘': "'",
        '“': '"',
        '”': '"',
        '«': '"',
        '»': '"',
        '—': ' - ',
        '–': '-',
        '…': '...',
        '\u00a0': ' ',
        '\u202f': ' ',
        'œ': 'oe',
        'Œ': 'OE',
        'æ': 'ae',
        'Æ': 'AE',
    }
    cleaned = text
    for orig, rep in replacements.items():
        cleaned = cleaned.replace(orig, rep)
    return cleaned

def html_to_plain_text(html_content: str) -> str:
    """Extracts clean text paragraphs from HTML."""
    soup = BeautifulSoup(html_content, "html.parser")
    for tag in soup(["script", "style"]):
        tag.decompose()
    
    text_blocks = []
    for el in soup.find_all(["h1", "h2", "h3", "h4", "p", "blockquote", "li"]):
        txt = el.get_text().strip()
        if txt:
            if el.name in ["h1", "h2"]:
                text_blocks.append(f"\n\n{'=' * 40}\n{txt.upper()}\n{'=' * 40}\n")
            elif el.name in ["h3", "h4"]:
                text_blocks.append(f"\n\n--- {txt} ---\n")
            else:
                text_blocks.append(txt)
    
    return "\n\n".join(text_blocks)

def export_to_txt(chapters: List[Dict[str, str]], title: str, author: str, output_path: str) -> str:
    """Exports book chapters to a clean UTF-8 text file."""
    lines = [
        "=" * 60,
        title.upper(),
        f"Auteur : {author}",
        "Édition du Domaine Public Propre",
        "=" * 60,
        "\n"
    ]
    for c in chapters:
        c_title = c.get("title", "Chapitre")
        lines.append(f"\n\n{'~' * 40}\n{c_title}\n{'~' * 40}\n")
        raw_html = c.get("html", "")
        lines.append(html_to_plain_text(raw_html))
    
    with open(output_path, "w", encoding="utf-8", errors="replace") as f:
        f.write("\n".join(lines))
    return output_path

def export_to_single_html(chapters: List[Dict[str, str]], title: str, author: str, output_path: str, lang: str = "fr") -> str:
    """Exports book chapters to an elegant single-file HTML document for offline reading."""
    toc_links = []
    content_blocks = []
    
    for idx, c in enumerate(chapters, 1):
        c_title = c.get("title", f"Chapitre {idx}")
        anchor = f"chap_{idx}"
        toc_links.append(f'<li><a href="#{anchor}">{c_title}</a></li>')
        content_blocks.append(f'<section id="{anchor}" class="chapter"><h2>{c_title}</h2>{c.get("html", "")}</section><hr/>')
    
    full_html = f"""<!DOCTYPE html>
<html lang="{lang}">
<head>
    <meta charset="utf-8"/>
    <meta name="viewport" content="width=device-width, initial-scale=1.0"/>
    <title>{title} - {author}</title>
    <style>
        {CLEAN_CSS}
        body {{ max-width: 780px; margin: 2rem auto; padding: 0 1.5rem; }}
        nav.toc {{ background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 12px; padding: 1.5rem; margin-bottom: 3rem; }}
        nav.toc ul {{ list-style-type: none; padding-left: 0; }}
        nav.toc li {{ margin: 0.4rem 0; }}
        nav.toc a {{ color: #0284c7; text-decoration: none; }}
        nav.toc a:hover {{ text-decoration: underline; }}
        header.book-header {{ text-align: center; border-bottom: 2px solid #e2e8f0; padding-bottom: 2rem; margin-bottom: 2.5rem; }}
        header.book-header h1 {{ font-size: 2.4rem; margin-bottom: 0.5rem; }}
        header.book-header p.author {{ font-size: 1.2rem; color: #64748b; font-style: italic; }}
    </style>
</head>
<body>
    <header class="book-header">
        <h1>{title}</h1>
        <p class="author">{author}</p>
        <p><small>Édition Domaine Public Propre</small></p>
    </header>

    <nav class="toc">
        <h3>Sommaire</h3>
        <ul>
            {''.join(toc_links)}
        </ul>
    </nav>

    <main>
        {''.join(content_blocks)}
    </main>
</body>
</html>"""
    with open(output_path, "w", encoding="utf-8", errors="replace") as f:
        f.write(full_html)
    return output_path

class EReaderPDF(FPDF):
    """Custom FPDF with header and footer for 6-inch e-readers or A4."""
    def __init__(self, book_title: str, book_author: str, is_ereader: bool = True):
        format_size = (90, 120) if is_ereader else "A4"
        super().__init__(format=format_size, unit="mm")
        self.book_title = clean_unicode_for_pdf(book_title[:40])
        self.book_author = clean_unicode_for_pdf(book_author[:30])
        self.is_ereader = is_ereader
        self.font_family_name = self._setup_unicode_fonts()
        self.set_auto_page_break(auto=True, margin=10 if is_ereader else 15)

    def _setup_unicode_fonts(self) -> str:
        win_fonts = r"C:\Windows\Fonts"
        if os.path.exists(os.path.join(win_fonts, "arial.ttf")):
            try:
                self.add_font("BookFont", fname=os.path.join(win_fonts, "arial.ttf"))
                if os.path.exists(os.path.join(win_fonts, "arialbd.ttf")):
                    self.add_font("BookFont", style="B", fname=os.path.join(win_fonts, "arialbd.ttf"))
                if os.path.exists(os.path.join(win_fonts, "ariali.ttf")):
                    self.add_font("BookFont", style="I", fname=os.path.join(win_fonts, "ariali.ttf"))
                return "BookFont"
            except Exception:
                pass
        return "Helvetica"

    def header(self):
        if self.page_no() > 1:
            self.set_font(self.font_family_name, "I" if self.font_family_name == "Helvetica" else "", 7 if self.is_ereader else 8)
            self.set_text_color(128, 128, 128)
            header_text = f"{self.book_title} - {self.book_author}"
            try:
                self.cell(0, 5, header_text, align="C")
            except Exception:
                safe_header = header_text.encode('latin-1', 'replace').decode('latin-1')
                self.cell(0, 5, safe_header, align="C")
            self.ln(6)

    def footer(self):
        self.set_y(-8 if self.is_ereader else -12)
        self.set_font(self.font_family_name, size=7 if self.is_ereader else 8)
        self.set_text_color(150, 150, 150)
        self.cell(0, 4, str(self.page_no()), align="C")

def export_to_pdf(chapters: List[Dict[str, str]], title: str, author: str, output_path: str, is_ereader: bool = True) -> str:
    """
    Exports book chapters to PDF formatted specifically for 6" e-readers (Kindle/Kobo)
    or standard A4.
    """
    pdf = EReaderPDF(book_title=title, book_author=author, is_ereader=is_ereader)
    fn = pdf.font_family_name
    
    clean_t = clean_unicode_for_pdf(title)
    clean_a = clean_unicode_for_pdf(author)

    # Cover / Title Page
    pdf.add_page()
    pdf.set_font(fn, "B", 15 if is_ereader else 24)
    pdf.set_text_color(20, 20, 20)
    pdf.ln(20 if is_ereader else 50)
    try:
        pdf.multi_cell(0, 7 if is_ereader else 12, text=clean_t, align="C")
    except Exception:
        pdf.multi_cell(0, 7 if is_ereader else 12, text=clean_t.encode('latin-1', 'replace').decode('latin-1'), align="C")

    pdf.ln(5)
    pdf.set_font(fn, "I", 10 if is_ereader else 14)
    pdf.set_text_color(100, 100, 100)
    try:
        pdf.cell(0, 6, text=clean_a, align="C")
    except Exception:
        pdf.cell(0, 6, text=clean_a.encode('latin-1', 'replace').decode('latin-1'), align="C")

    pdf.ln(15)
    pdf.set_font(fn, size=7 if is_ereader else 10)
    pdf.set_text_color(150, 150, 150)
    pdf.cell(0, 5, text="~ Edition Domaine Public Propre ~", align="C")

    # Chapters
    font_body_size = 8.5 if is_ereader else 11
    line_height = 4.8 if is_ereader else 6

    for c in chapters:
        pdf.add_page()
        c_title = clean_unicode_for_pdf(c.get("title", "Chapitre"))
        pdf.set_font(fn, "B", 11 if is_ereader else 16)
        pdf.set_text_color(20, 20, 20)
        try:
            pdf.multi_cell(0, 6 if is_ereader else 9, text=c_title, align="C")
        except Exception:
            pdf.multi_cell(0, 6 if is_ereader else 9, text=c_title.encode('latin-1', 'replace').decode('latin-1'), align="C")
        pdf.ln(4)

        raw_html = c.get("html", "")
        soup = BeautifulSoup(raw_html, "html.parser")
        paragraphs = soup.find_all(["p", "blockquote", "li"])
        
        pdf.set_font(fn, size=font_body_size)
        pdf.set_text_color(40, 40, 40)

        for p in paragraphs:
            txt = p.get_text().strip()
            if txt:
                clean_txt = clean_unicode_for_pdf(re.sub(r'\s+', ' ', txt))
                try:
                    pdf.multi_cell(0, line_height, text=clean_txt)
                    pdf.ln(2)
                except Exception:
                    ascii_txt = clean_txt.encode('latin-1', 'replace').decode('latin-1')
                    pdf.multi_cell(0, line_height, text=ascii_txt)
                    pdf.ln(2)

    pdf.output(output_path)
    return output_path

def convert_epub_to_format(epub_path: str, target_format: str, output_dir: str) -> str:
    """
    Converts an existing clean EPUB into target_format:
    - 'epub' / 'kindle_epub' : Returns the EPUB itself (fully compatible with Amazon Send to Kindle)
    - 'pdf_ereader' : 6" e-reader formatted PDF (90x120mm)
    - 'pdf_a4' : Standard A4 PDF
    - 'txt' : Clean plain text file
    - 'html' : Standalone single-file HTML document
    """
    if target_format in ("epub", "kindle_epub", "kindle"):
        return epub_path

    book = epub.read_epub(epub_path)
    titles = book.get_metadata('DC', 'title')
    title = titles[0][0] if titles else os.path.basename(epub_path).replace(".epub", "")
    
    creators = book.get_metadata('DC', 'creator')
    author = creators[0][0] if creators else "Auteur Inconnu"

    languages = book.get_metadata('DC', 'language')
    lang = languages[0][0] if languages else "fr"

    from epub_cleaner import is_document_item, clean_html_content
    doc_items = [item for item in book.get_items() if is_document_item(item)]
    chapters = []

    for doc in doc_items:
        fname = doc.get_name().lower()
        if fname in ("toc.xhtml", "nav.xhtml", "toc.ncx", "content.opf", "cover.xhtml"):
            continue

        content = doc.get_content().decode("utf-8", errors="replace")
        cleaned = clean_html_content(content, lang=lang)
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

    base_name = os.path.splitext(os.path.basename(epub_path))[0]
    os.makedirs(output_dir, exist_ok=True)

    if target_format == "pdf_ereader":
        out_file = os.path.join(output_dir, f"{base_name} (Liseuse 6p).pdf")
        return export_to_pdf(chapters, title, author, out_file, is_ereader=True)
    elif target_format == "pdf_a4":
        out_file = os.path.join(output_dir, f"{base_name} (Format A4).pdf")
        return export_to_pdf(chapters, title, author, out_file, is_ereader=False)
    elif target_format == "txt":
        out_file = os.path.join(output_dir, f"{base_name}.txt")
        return export_to_txt(chapters, title, author, out_file)
    elif target_format == "html":
        out_file = os.path.join(output_dir, f"{base_name}.html")
        return export_to_single_html(chapters, title, author, out_file, lang=lang)
    else:
        return epub_path
