# 📄 paperless-pipeline

Pipeline automatisé de numérisation, classification et renommage de documents
administratifs français via Paperless-ngx + Paperless-AI + Kimi K2.5.

---

## 🧠 Architecture

```
DS-940DW
↓ (scan vers dossier consume)
data/consume/
↓
Paperless-ngx (OCR Tesseract — français)
↓
Paperless-AI (Kimi K2.5 — classification + renommage)
↓
data/export/
├── documents classés et renommés
└── a-verifier/   ← confidence < 0.7
```

---

## 📦 Prérequis

- Docker + Docker Compose
- Une clé API Kimi K2.5 (Moonshot)
- Python 3 (pour le script export)

---

## 🚀 Installation en 5 minutes

### 1. Cloner le repo

```bash
git clone git@github.com:ton-user/paperless-pipeline.git
cd paperless-pipeline
```

### 2. Créer le fichier `.env`

```bash
cp .env.example .env
```

Ouvre `.env` et remplis chaque valeur.

#### Générer des mots de passe solides

Lance ces commandes dans ton terminal et colle les résultats dans `.env` :

```bash
# POSTGRES_PASSWORD
openssl rand -base64 24

# PAPERLESS_SECRET_KEY (doit être longue)
openssl rand -base64 48

# PAPERLESS_ADMIN_PASSWORD
openssl rand -base64 16
```

> ⚠️ Note ces valeurs dans un gestionnaire de mots de passe
> (Bitwarden, Apple Keychain, etc.) — tu en auras besoin plus tard.

#### Récupérer ta clé API Kimi K2.5

1. Va sur [platform.moonshot.cn](https://platform.moonshot.cn)
2. Connecte-toi → **API Keys** → **Create API Key**
3. Copie la clé générée (elle ne s'affiche qu'une seule fois)
4. Colle-la dans `.env` :

```bash
KIMI_API_KEY=sk-xxxxxxxxxxxxxxxxxxxxxxxx
```

> Pas de guillemets — la valeur brute suffit.

### 3. Lancer les containers

```bash
docker compose up -d
```

Vérifie que tout tourne :

```bash
docker compose ps
```

Tu dois voir 4 services `running` : `broker`, `db`, `webserver`, `paperless-ai`.

### 4. Créer le token API Paperless

C'est la seule étape manuelle — à faire une seule fois.

1. Ouvre [http://localhost:8000](http://localhost:8000)
2. Connecte-toi avec `PAPERLESS_ADMIN_USER` / `PAPERLESS_ADMIN_PASSWORD`
3. Va dans **Settings** → **API Tokens** → **Create Token**
4. Copie le token généré
5. Colle-le dans `.env` :

```bash
PAPERLESS_API_TOKEN=ton_token_ici
```

6. Redémarre les containers pour prise en compte :

```bash
docker compose restart
```

---

## ⚡ Aliases — démarrage rapide

Ajoute ces aliases dans ton `~/.zshrc` pour démarrer et arrêter
le pipeline en une commande :

```bash
# paperless-pipeline
alias paperless-start='cd ~/Projects/paperless-pipeline && docker compose up -d && echo "✅ Paperless démarré sur http://localhost:8000"'
alias paperless-stop='cd ~/Projects/paperless-pipeline && docker compose down && echo "🛑 Paperless arrêté"'
```

> Adapte le chemin `~/Projects/paperless-pipeline` à ton setup.

Recharge ton shell :

```bash
source ~/.zshrc
```

Utilisation :

```bash
paperless-start   # démarre tous les containers
paperless-stop    # arrête proprement
```

---

## 📥 Workflow de numérisation

### 1. Scanner tes documents

Configure ton Brother DS-940DW pour déposer les scans
directement dans `data/consume/` :

- Format : **PDF**
- Résolution : **300 DPI minimum**
- Mode : **Noir & Blanc** pour les docs texte, **Couleur** pour les docs avec logos

### 2. Laisser Paperless traiter

Dès qu'un fichier apparaît dans `data/consume/` :

1. **Paperless-ngx** lance l'OCR Tesseract en français
2. **Paperless-AI** envoie le texte extrait à Kimi K2.5
3. Kimi retourne un JSON structuré (titre, type, correspondant, tags, confidence)
4. Paperless applique les métadonnées et renomme le fichier

Délai moyen par document : **1 à 2 minutes**.

### 3. Exporter les documents traités

```bash
chmod +x scripts/export.sh
./scripts/export.sh
```

Les documents sont exportés dans `data/export/` :
```
data/export/
├── 2019-01_facture_edf.pdf
├── 2022-03_bulletin-de-paie_entreprise-xyz.pdf
├── 2020-01_document-fiscal_dgi.pdf
└── a-verifier/
└── ...   ← confidence < 0.7, à traiter manuellement
```

---

## 📂 Structure du repo
```
paperless-pipeline/
├── docker-compose.yml
├── .env.example
├── .gitignore
├── paperless-ai/
│   └── config.yml
├── scripts/
│   └── export.sh
└── README.md
```
---

## 🔧 Configuration avancée

### Changer le seuil de confidence

Dans `scripts/export.sh`, modifie :

```bash
MIN_CONFIDENCE=0.7
```

- `0.9` → très strict, beaucoup de docs dans `a-verifier/`
- `0.5` → permissif, moins de vérification manuelle

### Changer de modèle LLM

Dans `docker-compose.yml` et `paperless-ai/config.yml` :

```yaml
OPENAI_MODEL: moonshot-v1-32k   # Kimi K2.5 — défaut
```

#### Basculer sur Claude (via LiteLLM)

Si tu veux utiliser Claude à la place de Kimi, il faut ajouter
un proxy LiteLLM car l'API Anthropic n'est pas nativement
compatible OpenAI. Non nécessaire avec Kimi.

### Langue OCR

Définie dans `docker-compose.yml` :

```yaml
PAPERLESS_OCR_LANGUAGE: fra
```

Pour des documents multilingues (ex. français + anglais) :

```yaml
PAPERLESS_OCR_LANGUAGE: fra+eng
```

---

## 🔒 Sécurité

- Le fichier `.env` n'est **jamais commité** (voir `.gitignore`)
- Les données (`data/`) ne sont **jamais commitées**
- Le pipeline tourne entièrement en **local** — aucun document
  ne transite vers un service tiers, seul le texte OCRisé
  est envoyé à l'API Kimi pour classification
- Hébergement Kimi : serveurs Moonshot AI (Chine)

> Si la confidentialité des données OCRisées est critique
> (ex. documents médicaux, jugements), envisage un modèle
> local via Ollama à la place de Kimi.

---

## 🐛 Dépannage

### Les containers ne démarrent pas

```bash
docker compose logs webserver
docker compose logs paperless-ai
```

### Un document n'est pas traité

Vérifie que le fichier est bien en PDF et non corrompu :

```bash
ls -la data/consume/
```

### Paperless-AI ne classe pas les documents

Vérifie que le token API est bien renseigné dans `.env`
et que les containers ont été redémarrés après :

```bash
docker compose restart paperless-ai
```

### Réinitialiser complètement

```bash
docker compose down -v   # supprime aussi les volumes
docker compose up -d
```

> ⚠️ Cette commande supprime toutes les données traitées.

---

## 📋 Récapitulatif des catégories de documents

| Catégorie | Exemples |
|---|---|
| Facture | EDF, Orange, SFR, eau |
| Bulletin de paie | Fiche de salaire mensuelle |
| Document fiscal | Avis d'imposition, déclaration |
| Relevé bancaire | Extrait de compte |
| Assurance | Attestation, contrat |
| Document médical | Compte-rendu, analyse |
| Mutuelle / Remboursement santé | Décompte CPAM, mutuelle |
| Contrat | Bail, CDI, CDD |
| Quittance de loyer | Reçu mensuel |
| Document employeur | Attestation, promesse d'embauche |
| Document Pôle Emploi / France Travail | Attestation, convocation |
| Titre d'identité | CNI, passeport |
| Carte grise / Document véhicule | Certificat d'immatriculation |
| Acte d'état civil | Naissance, mariage, PACS |
| Diplôme | Bac, licence, master |
| Bulletin scolaire | Relevé de notes trimestriel |
| Document scolaire | Certificat de scolarité |
| Jugement / Acte juridique | Décision tribunal |
| Devis / Bon de commande | Devis artisan, commande |
| Courrier administratif | CAF, préfecture, mairie |

---

## 📜 Licence

MIT — usage personnel.
