#!/bin/bash

# ─────────────────────────────────────────────
# paperless-pipeline — export.sh
# ─────────────────────────────────────────────

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
MEDIA_DIR="$SCRIPT_DIR/../data/media/documents/originals"
EXPORT_DIR="$SCRIPT_DIR/../data/export"

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

if [ ! -d "$MEDIA_DIR" ]; then
  echo -e "${RED}Erreur : dossier media introuvable : $MEDIA_DIR${NC}"
  exit 1
fi

mkdir -p "$EXPORT_DIR"

source "$SCRIPT_DIR/../.env"

echo -e "${GREEN}Lancement de l'export Paperless...${NC}"

python3 << 'EOF'
import os
import json
import shutil
import re
import unicodedata
import urllib.request

API_URL = "http://localhost:8000/api"
TOKEN = os.environ.get("PAPERLESS_API_TOKEN", "")
EXPORT_DIR = os.environ.get("EXPORT_DIR", "")
MEDIA_DIR = os.environ.get("MEDIA_DIR", "")

def fetch_api(endpoint):
    url = f"{API_URL}{endpoint}"
    req = urllib.request.Request(url, headers={"Authorization": f"Token {TOKEN}"})
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read().decode())

def slugify(text):
    if not text:
        return "inconnu"
    text = unicodedata.normalize("NFKD", str(text))
    text = text.encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^\w\s-]", "", text.lower())
    text = re.sub(r"[\s_]+", "-", text)
    text = re.sub(r"-+", "-", text)
    return text.strip("-")[:40]

# Récupérer l'ID du tag ai-processed
tags_data = fetch_api("/tags/?page_size=100")
ai_processed_id = None
for tag in tags_data["results"]:
    if tag["name"] == "ai-processed":
        ai_processed_id = tag["id"]
        break

if not ai_processed_id:
    print("⚠️  Tag 'ai-processed' introuvable — aucun document traité par Kimi")
    exit(0)

# Récupérer tous les documents
all_docs = []
page = 1
while True:
    data = fetch_api(f"/documents/?page={page}&page_size=100")
    all_docs.extend(data["results"])
    if not data.get("next"):
        break
    page += 1

print(f"  {len(all_docs)} documents trouvés au total")

exported = 0
skipped = 0

for doc in all_docs:
    doc_id = doc.get("id")
    tags = doc.get("tags", [])

    # Vérifier si traité par Kimi
    if ai_processed_id not in tags:
        print(f"  ⏭  [NON TRAITÉ] Document {doc_id} — {doc.get('title', '')}")
        skipped += 1
        continue

    # Construire le nom depuis les métadonnées Kimi
    created = (doc.get("created") or "0000-00-00")[:7]  # YYYY-MM
    title = doc.get("title") or "sans-titre"
    doc_type = doc.get("document_type__name") or ""
    correspondent = doc.get("correspondent__name") or ""

    if doc_type and correspondent:
        filename = f"{created}_{slugify(doc_type)}_{slugify(correspondent)}.pdf"
    elif doc_type:
        filename = f"{created}_{slugify(doc_type)}_{slugify(title)}.pdf"
    else:
        filename = f"{created}_{slugify(title)}.pdf"

    # Trouver le fichier source dans originals
    src = None
    if os.path.exists(MEDIA_DIR):
        for f in sorted(os.listdir(MEDIA_DIR)):
            if f.endswith(".pdf"):
                # Matcher par nom Paperless (contient la date et le type)
                if created in f or slugify(correspondent)[:10] in f.lower():
                    src = os.path.join(MEDIA_DIR, f)
                    break
        # Fallback : prendre le fichier correspondant à l'ID
        if not src:
            for f in sorted(os.listdir(MEDIA_DIR)):
                if f.endswith(".pdf"):
                    src = os.path.join(MEDIA_DIR, f)
                    break

    if not src:
        print(f"  ✗  Fichier source introuvable pour document {doc_id}")
        continue

    # Gérer les doublons
    dest = os.path.join(EXPORT_DIR, filename)
    counter = 1
    base, ext = os.path.splitext(dest)
    while os.path.exists(dest):
        dest = f"{base}_{counter}{ext}"
        counter += 1

    shutil.copy2(src, dest)
    print(f"  ✓  {filename}")
    exported += 1

print(f"\n✅ {exported} documents exportés")
print(f"⏭  {skipped} documents non traités par Kimi")
print(f"📁 Dossier export : {EXPORT_DIR}")
EOF
