#!/bin/bash

# ─────────────────────────────────────────────
# paperless-pipeline — export.sh
# Exporte les documents traités vers le dossier
# de destination final (iCloud ou local)
# ─────────────────────────────────────────────

set -euo pipefail

# ── Configuration ────────────────────────────
MEDIA_DIR="$(dirname "$0")/../data/media/documents/originals"
EXPORT_DIR="$(dirname "$0")/../data/export"
MIN_CONFIDENCE=0.7

# ── Couleurs terminal ─────────────────────────
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

# ── Vérifications ─────────────────────────────
if [ ! -d "$MEDIA_DIR" ]; then
  echo -e "${RED}Erreur : dossier media introuvable : $MEDIA_DIR${NC}"
  exit 1
fi

mkdir -p "$EXPORT_DIR"
mkdir -p "$EXPORT_DIR/a-verifier"

# ── Export via API Paperless ──────────────────
echo -e "${GREEN}Lancement de l'export Paperless...${NC}"

source "$(dirname "$0")/../.env"

RESPONSE=$(curl -s \
  -H "Authorization: Token ${PAPERLESS_API_TOKEN}" \
  "${PAPERLESS_URL}/api/documents/?page_size=1000")

TOTAL=$(echo "$RESPONSE" | python3 -c "import sys,json; print(json.load(sys.stdin)['count'])")
echo -e "${GREEN}${TOTAL} documents trouvés${NC}"

echo "$RESPONSE" | python3 - << 'EOF'
import sys
import json
import os
import shutil
import re
import unicodedata

data = json.load(sys.stdin)
export_dir = os.environ.get("EXPORT_DIR", "./data/export")
media_dir = os.environ.get("MEDIA_DIR", "./data/media/documents/originals")
min_confidence = float(os.environ.get("MIN_CONFIDENCE", "0.7"))

def slugify(text):
    text = unicodedata.normalize("NFKD", text)
    text = text.encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^\w\s-]", "", text.lower())
    text = re.sub(r"[\s_]+", "-", text)
    return text[:80]

exported = 0
flagged = 0

for doc in data["results"]:
    title = doc.get("title", "sans-titre")
    doc_id = doc.get("id")
    created = doc.get("created", "0000-00-00")[:7]  # YYYY-MM
    correspondent = doc.get("correspondent__name", "inconnu") or "inconnu"
    doc_type = doc.get("document_type__name", "autre") or "autre"
    confidence = float(doc.get("custom_fields", {}).get("confidence", 1.0) or 1.0)

    filename = f"{created}_{slugify(doc_type)}_{slugify(correspondent)}.pdf"
    src = os.path.join(media_dir, f"{doc_id:07d}.pdf")

    if confidence < min_confidence:
        dest = os.path.join(export_dir, "a-verifier", filename)
        flagged += 1
    else:
        dest = os.path.join(export_dir, filename)
        exported += 1

    if os.path.exists(src):
        shutil.copy2(src, dest)
        print(f"  ✓ {filename}" if confidence >= min_confidence else f"  ⚠ [À VÉRIFIER] {filename}")
    else:
        print(f"  ✗ Fichier source introuvable : {src}")

print(f"\n✅ {exported} documents exportés")
print(f"⚠️  {flagged} documents à vérifier (confidence < {min_confidence})")
print(f"📁 Dossier export : {export_dir}")
EOF
