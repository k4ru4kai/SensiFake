# SensiFake

Progetto di Computer Vision sulla sensibilità dei contenuti nella rilevazione di immagini reali e sintetiche.

## Annotazione manuale

L'unica applicazione supportata è `scripts/annotation/app.py`. Avviala dalla
radice del repository con:

```bash
uv run streamlit run scripts/annotation/app.py
```

Consulta la [guida annotazione](docs/annotation.md) per lo stato attuale e la
passaggio di revisione offline e le estensioni future.

## Dove trovare cosa

| Percorso | Contenuto |
|---|---|
| `scripts/annotation/app.py` | Unica applicazione di annotazione supportata |
| [annotations/](annotations/README.md) | Dati di annotazione esistenti e struttura futura |
| [data/](data/README.md) | Immagini, manifest, esperimenti di raccolta e archivi |
| [docs/](docs/README.md) | Guide operative, protocollo e report |
| [notebooks/](notebooks/README.md) | Esperimenti VLM e benchmark |
| [scripts/](scripts/README.md) | Raccolta, selezione, manifest e comandi offline |
| `scripts/annotation/` | Logica Python del nuovo annotatore |
| `configs/` | Configurazioni delle sorgenti |
| [scripts/legacy/](scripts/legacy/README.md) | Utility storiche di assegnazione |
| `tests/` | Test automatici |

## Dati, ricerca e sviluppo

- [Stato e provenienza dei dati](docs/data_manifest.md): conteggi e limiti dell’audit documentato; non prova la presenza dei dati nel tuo clone.
- [Protocollo del dataset](docs/dataset_protocol.md).
- [Raccolta e workflow completi](docs/workflows.md).
- [Report del progetto](docs/project_report.md) e [piano del dataset](docs/dataset_plan.md).

Per sviluppare: `uv sync --group dev`. Alcuni test del repository richiedono
collezioni locali non distribuite con Git.
