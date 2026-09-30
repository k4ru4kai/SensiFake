# Script per funzione

Eseguire i comandi dalla radice del repository.

| Cartella | Contenuto |
|---|---|
| `annotation/` | Nuovo annotatore, schema, database, import batch e pacchetti |
| `collection/` | Raccolta in streaming e adattatori OpenFake/SID-Set |
| `datasets/` | Audit e manifest unificato; selezione RRDataset |
| `legacy/` | Utility storiche per le assegnazioni |
| `tools/` | Migrazioni e manutenzione amministrativa esplicite |

## Comandi principali

- Annotazione: `uv run streamlit run scripts/annotation/app.py`
- Pacchetti: `uv run python scripts/annotation/manage_packages.py --help`
- Raccolta: `uv run python scripts/collection/stream_collect.py --help`
- Manifest: `uv run python scripts/datasets/build_unified_manifest.py --help`
- Selezione RRDataset: `uv run python scripts/datasets/select_rrdataset_batch.py --help`

In `annotation/`, `annotation_schema.py` conserva validatori condivisi con il vecchio flusso; `annotation_database.py` gestisce SQLite; `import_batches.py` valida i batch; `annotation_packages.py` prepara e riunisce i pacchetti. `manage_packages.py` espone questi ultimi comandi al terminale.

Le assegnazioni storiche si riproducono con `scripts/legacy/build_gold_silver_assignment.py` e `scripts/legacy/build_human_train_assignment.py`. Non definiscono il nuovo golden set.

Vedere la [guida annotazione](../docs/annotation.md), i [workflow](../docs/workflows.md),
la [guida offline](../docs/offline_annotation.md) e le [utility storiche](legacy/README.md).
