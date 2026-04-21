# Export Workflow Example

This example documents how to use filethat's export scripts to build a
structured archive of your classified documents and sync them to an external
storage service.

The workflow shown here was designed for **Digiposte** (La Poste's personal
digital vault), but the scripts are generic and work with any destination:
Dropbox, Google Drive, a NAS, an S3 bucket, etc.

## Prerequisites

- filethat is running and has classified at least some documents
- Documents are tagged `ai:processed` (confidence ≥ 0.7) or `ai:to-check`
- `make init-referential` has been run at least once

## How it works

The export pipeline has three steps:

```
Paperless-ngx                scripts/               data/export/
(classified docs)  ──────►  export.py     ──────►  Invoice/
                                                     Payslip/
                                                     Tax-document/
                                                     ...
                             mark_exported.py  ───►  tags doc as workflow:exported
                             archive.py        ───►  moves to archive/<timestamp>/
```

### Step 1 — Export

Downloads classified PDFs from Paperless and organises them by document type:

```bash
make export
# or, to also include documents pending review:
make export-all
```

Output structure:

```
data/export/
├── Invoice/
│   ├── 2024-01_Invoice_EDF.pdf
│   └── 2024-02_Invoice_Free.pdf
├── Payslip/
│   └── 2024-01_Payslip_Capgemini.pdf
├── Tax-document/
│   └── 2023-01_Tax-document_DGFiP.pdf
└── index.csv
```

The `index.csv` file is regenerated on every run and lists all exported files
with their metadata (folder, filename, period, type, correspondent, size).

### Step 2 — Upload to your destination

At this point, copy or sync `data/export/` to your destination manually or
via a script. Examples:

```bash
# Dropbox via CLI
dropbox_uploader.sh upload data/export/ /filethat/

# Rclone to any cloud storage
rclone copy data/export/ remote:filethat-archive

# Manual: open data/export/ in Finder/Explorer and drag to your vault
```

For **Digiposte** specifically: open the Digiposte web app, navigate to your
vault, and upload the contents of each folder manually.

### Step 3 — Mark as exported

Once uploaded, tag the corresponding Paperless documents as exported so they
are excluded from future export runs:

```bash
make mark-exported
# or, to preview without making changes:
docker compose exec classifier python scripts/mark_exported.py --dry-run
```

### Step 4 — Archive

Move the exported files to a timestamped archive folder to keep the export
directory clean for the next cycle:

```bash
make archive
```

Output:

```
data/export/
└── archive/
    └── 2024-03-15_10-30-00/
        ├── Invoice/
        ├── Payslip/
        ├── Tax-document/
        ├── index.csv
        └── README.md
```

### Steps 3+4 in one command

```bash
make archive-and-mark
```

## Adding your own correspondents

If you have personal or local correspondents (your landlord, your employer,
a local utility provider) that are not in the generic `config/fr-admin/`
referential, create a local override file:

```bash
cp config/fr-admin/correspondents.yaml config/fr-admin/correspondents.local.yaml
```

Edit `correspondents.local.yaml` to add your entries:

```yaml
- canonical: "My Landlord"
  aliases: ["My Landlord SCI", "Landlord Management"]
  category: "housing"
```

This file is gitignored and will be merged automatically at startup.

## Cleaning up old archives

```bash
make trash-archives
```

This will ask for confirmation before permanently deleting all timestamped
archives under `data/export/archive/`.
