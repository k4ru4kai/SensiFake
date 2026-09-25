# Comandi del progetto

Eseguire dalla radice: `uv run python scripts/<nome>.py --help`.

| Script | Scopo |
|---|---|
| `stream_collect.py` | Raccolta delle immagini dalle sorgenti configurate |
| `select_rrdataset_batch.py` | Preparazione della selezione RRDataset |
| `build_unified_manifest.py` | Audit e manifest unico |
| `offline_annotations.py` | Preparazione, snapshot e merge dei pacchetti offline |
| `build_gold_silver_assignment.py` | Assegnazioni gold/silver |
| `build_human_train_assignment.py` | Task individuali del workflow precedente |
| `source_adapters/` | Adattatori delle sorgenti usati dal collector |

Le operazioni sui dataset richiedono i dati locali indicati nelle configurazioni.
Vedere [workflow](../docs/workflows.md) e [guida offline](../docs/offline_annotation.md).
