# 📚 Bibliothèque Libre & Générateur d'EPUB Propre

[![Python](https://img.shields.io/badge/Python-3.9%2B-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.100%2B-009688.svg)](https://fastapi.tiangolo.com/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Kindle Compatible](https://img.shields.io/badge/Amazon%20Kindle-100%25%20Compatible-orange.svg)](https://www.amazon.com/sendtokindle)

Un outil complet et élégant pour **rechercher n'importe quel livre dans le domaine public mondial**, générer automatiquement une **édition EPUB propre et typographiée de qualité publication** (sans mentions légales intrusives, avec espaces insécables et couverture typographique), et **traduire l'ouvrage dans n'importe quelle langue** à la demande.

---

## 🌟 Fonctionnalités Principales

### 1. 🔍 Recherche Universelle Domaine Public (Multi-Catalogues en Parallèle)
Interroge simultanément et en quelques millisecondes :
- **Project Gutenberg** via l'API officielle Gutendex (70 000+ chefs-d'œuvre de référence avec téléchargements directs).
- **Internet Archive** (millions d'écrits historiques et numérisations mondiales).
- **Wikisource (Wikimedia)** (textes intégraux authentifiés en français, latin, grec ancien, etc.).
- **Standard Ebooks** (éditions d'art avec typographie soignée).
- *Filtrage linguistique précis* : Français, Anglais, Allemand, Espagnol, Italien, Latin, Grec ancien, Russe, Chinois, Arabe, etc.

### 2. 📖 Générateur d'EPUB Propre & Publication Typographique
- **Élimination des bannières** : suppression automatique des avertissements juridiques et en-têtes/pieds de page Gutenberg, Archive.org et Wikisource.
- **Règles typographiques françaises** : insertion automatique des espaces insécables (`&nbsp;`) avant les ponctuations doubles (`:`, `;`, `!`, `?`, `»`) et après `«`.
- **Couverture Typographique Élégante** : génération automatique d'une couverture vectorielle SVG haute définition avec cadre classique, titre et auteur pour les livres sans couverture d'origine.
- **Conformité Liseuses** : 100% compatible avec Amazon Kindle (*Send to Kindle*), Kobo, Apple Books, Calibre, Tolino et PocketBook.

### 3. 📑 Choix du Format de Sortie Multi-Supports
- 📱 **EPUB Standard** : format e-reader universel.
- 📦 **EPUB Kindle** : optimisé pour le service officiel Amazon *Send to Kindle*.
- 📄 **PDF Spécial Liseuse 6" (90x120 mm)** : ratio d'aspect idéal pour les écrans Kindle Paperwhite et Kobo Clara, sans zoom ni défilement.
- 📑 **PDF Grand Format (A4)** : prêt pour impression ou lecture confortable sur PC et tablette.
- 📝 **Texte Brut (TXT)** : fichier épuré en encodage UTF-8.
- 🌐 **HTML Autonome** : document unique hors-ligne, lisible dans n'importe quel navigateur web.

### 4. 🌍 Traduction Intelligente Multi-Moteurs
- **Détection d'édition existante** : vérifie d'abord si une traduction humaine officielle existe déjà dans le domaine public dans la langue cible (Gutenberg/Wikisource).
- **Moteur de traduction avec secours automatique** : traduction intégrale combinant Google Translate (sans limite de quota) et MyMemory pour une fiabilité absolue sur les livres complets.
- **Préservation de la structure** : conservation intacte des titres, chapitres, citations et dialogues.

### 5. 🖥️ Liseuse Web Intégrée & Gestion de Bibliothèque
- Liseuse fluide avec navigation par chapitre, table des matières, mode Jour / Sépia / Nuit (mémorisé dans le navigateur) et réglage de la taille de police.
- Traduction de chapitre à la volée en 1 clic pendant la lecture.
- Gestionnaire de bibliothèque locale avec prévisualisation des couvertures, filtres par format, suppression de livres et import par glisser-déposer de fichiers personnels (`.epub`, `.txt`).

---

## 🚀 Démarrage Rapide

### Prérequis
- Python 3.9 ou supérieur.
- Installez les dépendances :
  ```bash
  pip install -r requirements.txt
  ```

### Méthode 1 : En 1 Clic (Lanceur Windows)
Double-cliquez sur :
👉 **`Lancer_Bibliotheque_EPUB.bat`**

Votre navigateur s'ouvrira automatiquement sur : `http://127.0.0.1:8000`.

---

### Méthode 2 : En Ligne de Commande (CLI)

#### 1. Lancer l'interface Web :
```bash
python pd_epub.py serve
```

#### 2. Rechercher un livre :
```bash
# Recherche universelle
python pd_epub.py search "Baudelaire"

# Recherche avec filtre de langue (fr, en, de, es, it, la...)
python pd_epub.py search "Les Fleurs du Mal" --lang fr

# Recherche sur une source spécifique (gutenberg, ia, wikisource, standard_ebooks)
python pd_epub.py search "Dante Divine Comédie" --source gutenberg --lang it
```

#### 3. Télécharger et générer une édition propre :
```bash
# Format EPUB standard par défaut
python pd_epub.py get "gutenberg:6318" --clean

# Format PDF taillé pour liseuse 6 pouces (Kindle / Kobo)
python pd_epub.py get "gutenberg:6318" --format pdf_ereader

# Format PDF A4
python pd_epub.py get "gutenberg:6318" --format pdf_a4
```

#### 4. Télécharger et traduire un livre :
```bash
# Traduire un livre anglais vers le français
python pd_epub.py get "gutenberg:1065" --translate fr

# Traduire un livre français vers l'anglais
python pd_epub.py get "gutenberg:6318" --translate en
```

#### 5. Gestion de la bibliothèque locale :
```bash
# Lister tous les documents disponibles
python pd_epub.py list

# Supprimer un document
python pd_epub.py delete "NomDuFichier.epub"

# Ouvrir le dossier des livres dans l'Explorateur Windows
python pd_epub.py folder
```

---

## 📂 Architecture du Projet

```text
public-domain-books/
├── Lancer_Bibliotheque_EPUB.bat  # Lanceur Windows 1-clic (détection py/python)
├── pd_epub.py                    # Point d'entrée CLI et lanceur de serveur
├── web_app.py                    # Serveur FastAPI & interface web moderne (SPA)
├── search_engine.py              # Moteur multi-sources (Gutendex, IA, Wikisource, SE)
├── downloader.py                 # Téléchargeur universel (EPUB, HTML, TXT)
├── epub_cleaner.py               # Nettoyeur typographique, insécables & couvertures SVG
├── epub_builder.py               # Constructeur EPUB3 à partir de texte brut / HTML
├── translator.py                 # Moteur de traduction multi-moteurs (Google + MyMemory)
├── format_exporter.py            # Convertisseur de formats (PDF 6", PDF A4, TXT, HTML)
├── library_manager.py            # Gestionnaire de fichiers locaux & couvertures
├── requirements.txt              # Dépendances Python
├── .gitignore                    # Fichiers et dossiers exclus du suivi git
└── epubs/                        # Dossier local de stockage de vos livres
```

---

## 📄 Licence

Ce projet est distribué sous licence libre **MIT**. Les textes téléchargés appartiennent au **domaine public** selon les législations en vigueur.
