# SensiFake

Progetto di Computer Vision sulla sensibilità dei contenuti nella rilevazione di immagini reali e sintetiche.

## Inizia da qui: annotazione locale

1. Installa Python 3.12 e [uv](https://docs.astral.sh/uv/), poi esegui `uv sync` dalla radice del repository mentre sei online.
2. Ricevi il tuo pacchetto `.sqlite3` da chi coordina il batch e salvalo sul disco locale. Immagini e database non sono inclusi nel clone.
3. Su Windows apri `start_annotation.bat`; su Linux/macOS esegui `bash start_annotation.sh`. Inserisci il percorso del tuo pacchetto quando richiesto.
4. Nel browser inserisci sempre lo stesso nome, scegli **Annotate** e salva ogni annotazione completata.

Dopo l’installazione, i launcher funzionano offline. In alternativa:

```bash
uv run --offline streamlit run app.py -- --storage "/percorso/assoluto/annotator-01.sqlite3"
```

Per importare un nuovo ZIP nel database principale:

```bash
uv run --offline streamlit run app.py
```

Il database principale predefinito resta `annotations/shared/sensifake.sqlite3`, per ritrovare il lavoro già esistente. Non spostare manualmente database aperti o file WAL.

## Dove trovare cosa

| Percorso | Contenuto |
|---|---|
| `app.py` | Annotatore attuale: batch, revisione ed esportazioni |
| [annotations/](annotations/README.md) | Database locali, pacchetti offline, risultati e annotazioni storiche |
| [data/](data/README.md) | Immagini, manifest, esperimenti di raccolta e archivi |
| [docs/](docs/README.md) | Guide operative, protocollo e report |
| [notebooks/](notebooks/README.md) | Esperimenti VLM e benchmark |
| [scripts/](scripts/README.md) | Raccolta, selezione, manifest e comandi offline |
| `sensifake_annotation/` | Logica Python dell’annotatore e delle assegnazioni |
| `configs/` | Configurazioni delle sorgenti |
| [legacy/](legacy/README.md) | Vecchio annotatore, mantenuto funzionante |
| `tests/` | Test automatici |

## Lavorare in tre

Segui la [guida offline](docs/offline_annotation.md) per preparare tre pacchetti distinti, restituire snapshot e riunire le annotazioni. Lo scambio dei file è manuale; non serve un server condiviso.

**Limite attuale:** il merge offline non importa le revisioni. Il riassetto delle cartelle non modifica questo comportamento. Per l’app condivisa e la revisione sullo stesso database consulta i [workflow dettagliati](docs/workflows.md#shared-manual-annotation).

## Dati, ricerca e sviluppo

- [Stato e provenienza dei dati](docs/data_manifest.md): conteggi e limiti dell’audit documentato; non prova la presenza dei dati nel tuo clone.
- [Protocollo del dataset](docs/dataset_protocol.md).
- [Raccolta e workflow completi](docs/workflows.md).
- [Report del progetto](docs/project_report.md) e [piano del dataset](docs/dataset_plan.md).

Per sviluppare: `uv sync --group dev`. Per verificare annotatore e flusso offline:

```bash
uv run --offline pytest tests/test_shared_annotation.py tests/test_offline_annotation.py tests/test_sensitivity_annotation.py tests/test_human_train_assignment.py
```

Alcuni test del repository richiedono collezioni locali non distribuite con Git. I vecchi comandi con `shared_annotation_app.py` e `annotation_app.py` restano disponibili tramite entry point di compatibilità.
