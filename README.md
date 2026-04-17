# 📄 paperless-pipeline

Pipeline automatisé de numérisation, OCR, classification et renommage de documents
administratifs français, avec export prêt à l'emploi vers Digiposte.

**Stack** : Paperless-ngx + OCR Tesseract + Claude Sonnet 4.6 (Anthropic) + Python.

---

## 🎯 Objectif

Numériser 10+ années d'archives administratives personnelles (300+ documents),
les classifier automatiquement avec une précision élevée, et les pousser dans
Digiposte dans une arborescence propre.

## 🧠 Architecture

```
Scanner Brother DS-940DW
       ↓ (scan PDF)
data/consume/
       ↓ (polling 30s)
Paperless-ngx (OCR Tesseract français)
       ↓ (API REST)
classifier (Python + Claude Sonnet 4.6)
       ↓
Paperless-ngx (métadonnées : type, correspondent, tags, date)
       ↓ (make export-digiposte)
data/export/digiposte/
├── Facture/
├── Bulletin-de-paie/
├── Quittance-de-loyer/
└── ...                    ← uploadé manuellement dans Digiposte
```

Le pipeline classifie chaque document selon :

- **23 types** de documents admin (Facture, Bulletin de paie, Document fiscal, etc.)
- **55 correspondants canoniques** (EDF, CAF, RIVP, DGFiP, banques, assureurs...)
- **Tags métier** (energie, loyer, sante, impot...)
- **Date** extraite du document (règles de priorité : émission, période, signature)
- **Confidence** calibrée (0-1), pilotant le tag système qui classe le doc

### Tags système

| Tag | Signification |
|---|---|
| `ai:processed` | Classifié avec confidence ≥ 0.7 — prêt à l'export |
| `ai:a-verifier` | Classifié avec confidence < 0.7 — à valider manuellement |
| `ai:failed` | Échec de classification — à reprocesser |
| `digiposte:uploaded` | Déjà uploadé dans Digiposte — exclu du prochain export |

---

## 📦 Prérequis

- Docker + Docker Compose (Colima, OrbStack ou Docker Desktop)
- `uv` (gestionnaire Python moderne) : `curl -LsSf https://astral.sh/uv/install.sh | sh`
- Une clé API Anthropic : [console.anthropic.com/settings/keys](https://console.anthropic.com/settings/keys)
- Python 3.12+ (pour le dev local, optionnel)

## 🚀 Installation

### 1. Cloner le repo

```bash
git clone git@github.com:MoSizzle87/paperless-pipeline.git
cd paperless-pipeline
```

### 2. Générer le lockfile Python

```bash
cd classifier
uv lock
cd ..
```

### 3. Créer le `.env`

```bash
cp .env.example .env
```

Édite `.env` et remplis les valeurs :

```bash
# Génère les mots de passe avec :
openssl rand -base64 24   # POSTGRES_PASSWORD
openssl rand -base64 48   # PAPERLESS_SECRET_KEY
openssl rand -base64 16   # PAPERLESS_ADMIN_PASSWORD
```

La clé Anthropic se récupère sur [console.anthropic.com](https://console.anthropic.com/settings/keys).

### 4. Premier démarrage

```bash
# Démarre broker, db, webserver (pas encore le classifier)
docker compose up -d broker db webserver

# Attends ~30s que Paperless-ngx initialise sa base
docker compose logs -f webserver
# Ctrl+C quand tu vois "Starting Gunicorn"
```

### 5. Récupérer le token API Paperless

1. Ouvre http://localhost:8000 et connecte-toi avec l'admin
2. Profil utilisateur → Auth Token → Generate
3. Copie le token dans `.env` à la ligne `PAPERLESS_API_TOKEN`

### 6. Build du classifier et démarrage complet

```bash
# Build du service Python
docker compose build classifier

# Démarre tout
make up

# Initialise le référentiel dans Paperless (23 types, 28 tags, 55 correspondants)
make init-referential

# Vérifie que le classifier tourne sans erreur
make logs
# Tu dois voir "Poller démarré..." puis des polls toutes les 60s
```

---

## ⚡ Alias shell recommandés

Dans ton `~/.zshrc` (ou `~/.bashrc`) :

```bash
# Fonctions d'orchestration paperless-pipeline
unalias paperless-start paperless-stop paperless-status 2>/dev/null

paperless-start() {
  local project_dir="$HOME/paperless-pipeline"
  if ! colima status &>/dev/null; then
    echo "🐳 Démarrage de Colima..."
    colima start || return 1
  fi
  (cd "$project_dir" && docker compose up -d) || return 1
  echo "✅ Paperless démarré sur http://localhost:8000"
}

paperless-stop() {
  local project_dir="$HOME/paperless-pipeline"
  (cd "$project_dir" && docker compose down)
  if colima status &>/dev/null; then
    colima stop
  fi
  echo "✅ Tout est arrêté"
}

paperless-status() {
  local project_dir="$HOME/paperless-pipeline"
  if colima status &>/dev/null 2>&1; then
    echo "🐳 Colima : running"
  else
    echo "🐳 Colima : stopped"
    return
  fi
  echo "📦 Containers :"
  (cd "$project_dir" && docker compose ps --format "  {{.Service}}: {{.State}}")
}
```

---

## 🔄 Workflow quotidien

### Étape 1 — Scanner

Configure ton scanner (exemple Brother DS-940DW) pour déposer directement
dans `data/consume/` :

- Format : PDF
- Résolution : 300 DPI
- Mode : Noir et blanc pour les docs texte, couleur pour les logos importants

Dès qu'un PDF arrive, Paperless le détecte (polling 30s), lance l'OCR, puis
le classifier le traite (polling 60s). Délai total moyen : **1 à 2 minutes par doc**.

### Étape 2 — Vérifier les docs à valider

Dans l'UI Paperless (http://localhost:8000), filtre sur le tag `ai:a-verifier`.
Ce sont les documents que Claude a classifiés avec une confidence < 0.7.

Pour chacun, vérifie / corrige et retire le tag `ai:a-verifier`.

S'il y a eu des échecs (`ai:failed`), relance :

```bash
make reprocess-failed
```

### Étape 3 — Export vers Digiposte

```bash
make export-digiposte
```

Génère une arborescence dans `data/export/digiposte/` :

```
data/export/digiposte/
├── Facture/
│   ├── 2019-01_Facture_EDF.pdf
│   ├── 2019-02_Facture_EDF.pdf
│   └── ...
├── Quittance-de-loyer/
├── Bulletin-de-paie/
└── index.csv
```

Le script filtre automatiquement les documents déjà taggés `digiposte:uploaded`
et ne génère que les nouveautés.

### Étape 4 — Upload dans Digiposte

1. Ouvre Digiposte dans ton navigateur
2. Coffre → Ajouter un élément → Importer un dossier
3. Sélectionne un dossier (par exemple `Facture/`) depuis Finder
4. Digiposte crée le dossier côté coffre et importe les PDFs à l'intérieur
5. Recommence pour chaque catégorie

⚠️ **Ne pas uploader un ZIP** : Digiposte stocke alors un fichier ZIP unique
non-visualisable. Toujours uploader les dossiers directement.

### Étape 5 — Marquer comme uploadé puis archiver

Une fois TOUS les dossiers uploadés dans Digiposte :

```bash
# Option 1 : tagger + archiver en une commande
make archive-and-mark

# Option 2 : séparément si tu veux vérifier entre les deux
make mark-uploaded
make archive-digiposte
```

`digiposte/` est vidé, les fichiers sont archivés dans `digiposte/archive/<timestamp>/`,
et les docs Paperless portent le tag `digiposte:uploaded` → ils ne seront plus
exportés au prochain run.

---

## 🛠️ Cibles Makefile

```
make help                  Liste complète des commandes

# Stack & maintenance
make up                    Démarre le stack
make down                  Arrête le stack
make clean                 Arrête + supprime tous les volumes (DESTRUCTIF)
make build                 Rebuild l'image classifier
make logs                  Tail des logs
make shell                 Shell dans le container classifier
make init-referential      (Re-)crée le référentiel Paperless (idempotent)
make backup                Export natif Paperless-ngx des docs+métadonnées

# Reprocessing
make reprocess-failed      Relance les docs taggés ai:failed
make reprocess-review      Relance les docs taggés ai:a-verifier

# Export Digiposte
make export-digiposte      Exporte les docs ai:processed
make export-digiposte-all  Idem + inclut les ai:a-verifier
make mark-uploaded         Tagge digiposte:uploaded les docs présents dans digiposte/
make archive-digiposte     Déplace digiposte/* vers digiposte/archive/<timestamp>/
make archive-and-mark      Tagge puis archive en une commande
make trash-archives        Supprime toutes les archives (confirmation requise)

# Stats
make stats                 Résumé depuis le JSONL (coût, volumes, confidence)
```

---

## 📂 Structure du repo

```
paperless-pipeline/
├── docker-compose.yml
├── .env.example
├── .gitignore
├── Makefile
├── README.md
├── classifier/
│   ├── Dockerfile
│   ├── pyproject.toml
│   ├── uv.lock
│   ├── src/pipeline/
│   │   ├── cli.py                   # Entry point (run, reprocess, stats)
│   │   ├── config.py                # Pydantic Settings
│   │   ├── schemas.py               # Modèles Pydantic I/O
│   │   ├── prompt.py                # Prompt système Claude + tool use
│   │   ├── llm_client.py            # SDK Anthropic avec prompt caching
│   │   ├── paperless_client.py      # Client REST Paperless-ngx
│   │   ├── normalizer.py            # Slugify + fuzzy matching Levenshtein
│   │   ├── referential.py           # Whitelist canonique + création auto
│   │   ├── classifier.py            # Orchestration du traitement d'un doc
│   │   ├── poller.py                # Boucle principale
│   │   ├── logging_setup.py         # Console + JSONL rotatif
│   │   └── referentials/
│   │       ├── correspondents_canonical.yaml
│   │       ├── document_types.yaml
│   │       └── tags.yaml
│   └── scripts/
│       ├── init_referential.py      # One-shot init Paperless
│       ├── export_digiposte.py      # Export vers arborescence Digiposte
│       ├── archive_digiposte.py     # Déplacement vers archive/<timestamp>/
│       └── mark_uploaded.py         # Tagging bulk digiposte:uploaded
├── data/                            # (gitignored)
│   ├── consume/                     # Dépôt des PDFs à traiter
│   ├── media/                       # Stockage interne Paperless (source de vérité)
│   ├── export/digiposte/            # Arborescence prête pour Digiposte
│   └── data/                        # Index de recherche Paperless
└── logs/
    └── pipeline.jsonl               # Audit log rotatif
```

---

## 🎛️ Configuration avancée

### Ajuster le seuil de confidence

Dans `docker-compose.yml`, service `classifier` :

```yaml
      CONFIDENCE_THRESHOLD: "0.7"
```

- `0.9` : très strict, beaucoup de docs en `ai:a-verifier`
- `0.7` : équilibré (défaut)
- `0.5` : permissif, peu de review manuelle

### Changer de modèle LLM

```yaml
      LLM_MODEL: claude-sonnet-4-6        # défaut, rapport qualité/prix optimal
      # LLM_MODEL: claude-opus-4-7         # plus précis, 5x plus cher
      # LLM_MODEL: claude-haiku-4-5        # moins cher mais précision en baisse
```

### Ajouter un correspondant canonique

Édite `classifier/src/pipeline/referentials/correspondents_canonical.yaml`,
ajoute une entrée avec alias :

```yaml
- canonical: "Nouveau Correspondant"
  aliases: ["Variante 1", "Autre variante"]
```

Puis re-init (idempotent) :

```bash
make init-referential
docker compose restart classifier
```

### Désactiver la création auto des correspondants

Dans `classifier/src/pipeline/referential.py`, méthode `resolve_correspondent`,
remplacer la branche de création Classe B par une exception. Le pipeline taguera
alors `ai:failed` les docs avec un correspondant non-whitelisté.

---

## 💰 Coûts estimés

Avec Claude Sonnet 4.6 + prompt caching Anthropic :

- **1er doc (cache miss)** : ~$0.017
- **Docs suivants (cache hit)** : ~$0.005 à $0.008

Pour **300 documents d'archive initiale** : ~$3 à $5.
Pour un **flux continu** de ~500 docs/an : ~$8 à $10/an.

---

## 🔒 Sécurité et confidentialité

- `.env` n'est JAMAIS commité (voir `.gitignore`)
- Le dossier `data/` n'est JAMAIS commité
- Tout le pipeline tourne **localement** (OCR + Paperless + orchestration)
- Seul le **texte OCR extrait** est envoyé à l'API Anthropic pour classification
- Les PDFs originaux ne quittent jamais ta machine
- Hébergement Anthropic : US / EU selon région

Pour un usage strict « 100% local » (documents très sensibles), remplacer Claude
par un modèle Ollama local (Qwen 2.5 72B, Llama 3.3) avec précision légèrement
inférieure sur le français admin.

---

## 🐛 Dépannage

### Le classifier crashe au démarrage avec « Tag ai:processed introuvable »

Le référentiel n'a pas été initialisé. Lance :

```bash
make init-referential
docker compose restart classifier
```

### Un doc reste dans `data/consume/` sans être traité

Vérifie les logs Paperless :

```bash
docker compose logs webserver --tail 50
```

Causes fréquentes : PDF corrompu, mot de passe sur le PDF, format non-supporté.

### Un doc est classé en `ai:failed`

Colle la ligne JSONL correspondante :

```bash
grep '"status":"failed"' logs/pipeline.jsonl | tail -1 | jq .
```

Le champ `error` te donne la cause (OCR vide, schéma LLM invalide, push Paperless échoué...).

Tu peux relancer après avoir compris/corrigé :

```bash
make reprocess-failed
```

### Reset complet

```bash
make clean    # supprime TOUTES les données (confirmation requise)
```

---

## 📜 Licence

MIT — usage personnel et pédagogique.

## 🙏 Crédits

- [Paperless-ngx](https://docs.paperless-ngx.com/) — système de gestion documentaire
- [Anthropic Claude](https://www.anthropic.com/claude) — classification LLM
- [uv](https://docs.astral.sh/uv/) — gestionnaire Python moderne
- [Docker](https://www.docker.com/) + [Colima](https://github.com/abiosoft/colima) ou [OrbStack](https://orbstack.dev/)
