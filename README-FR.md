# filethat

**Transformez le chaos de vos documents en archive structurée — grâce aux LLMs.**

filethat est un pipeline open-source de classification automatique de documents
administratifs. Il se connecte à [Paperless-ngx](https://docs.paperless-ngx.com/),
lit le texte extrait par OCR, appelle un LLM pour en extraire les métadonnées
structurées, et les réécrit dans Paperless — titre, date, émetteur, type de
document, tags.

Pour la documentation complète, voir [README.md](README.md).

---

## Démarrage rapide

```bash
git clone https://github.com/mogassama/filethat.git
cd filethat
cp .env.example .env        # remplir les clés API
make up                     # démarre Paperless-ngx + le classifier
make init-referential       # crée les types, tags et correspondants dans Paperless
```

Ouvrir http://localhost:8000, déposer un PDF dans le dossier consume, et
observer la classification automatique.

---

## Configuration minimale

```bash
LLM_PROVIDER=anthropic          # ou : openai
LLM_MODEL=claude-sonnet-4-6     # ou : gpt-4o
LLM_API_KEY=sk-ant-...          # clé API du provider choisi
LANGUAGE=fr                     # langue des labels et des dossiers d'export
```

---

## Cas d'usage : export vers un coffre-fort numérique

filethat classe vos documents dans Paperless. Une fois classifiés, vous pouvez
les exporter vers n'importe quel service de stockage externe (coffre-fort
numérique, Dropbox, Google Drive, NAS, etc.) en suivant le workflow d'export
inclus :

```bash
make export           # exporte les docs classifiés vers data/export/
make mark-exported    # tagge les docs exportés
make archive          # archive le dossier d'export
```

Voir [examples/export-workflow/README.md](examples/export-workflow/README.md)
pour le guide complet.

---

## Preset français

Le preset `config/fr-admin/` est inclus et couvre les documents administratifs
français courants :

- 23 types de documents (facture, bulletin de paie, avis d'imposition, etc.)
- ~50 correspondants canoniques (EDF, CAF, CPAM, URSSAF, DGFiP, banques, assureurs, etc.)
- Tags thématiques (energie, logement, sante, emploi, etc.)

Pour ajouter vos correspondants personnels (bailleur, employeur, etc.) sans
modifier le preset partagé :

```bash
cp config/fr-admin/correspondents.local.yaml.example \
   config/fr-admin/correspondents.local.yaml
# éditer correspondents.local.yaml — ce fichier est gitignorée
```

---

## Licence

MIT — voir [LICENSE](LICENSE).
