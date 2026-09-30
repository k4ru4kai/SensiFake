# Annotazione manuale

L'unica applicazione di annotazione supportata è
[`scripts/annotation/app.py`](../scripts/annotation/app.py). Dalla radice del
repository, avviala con:

```bash
uv run streamlit run scripts/annotation/app.py
```

I risultati storici restano conservati. Non avviare annotatori storici
recuperati dalla cronologia Git. Alcune utility storiche di assegnazione,
incluso `scripts/legacy/human_train_assignment.py`, possono restare perché il
codice corrente di importazione usa ancora i relativi metadati.

## Struttura prevista

Il prossimo passo del workflow è organizzare lo stato operativo con un database
SQLite master, pacchetti offline da distribuire e un processo successivo per
unire i pacchetti restituiti. Questa migrazione non è ancora attiva; i dati
esistenti non sono stati spostati.

```text
annotations/
    master/                 stato SQLite autorevole del progetto
    packages/
        outgoing/            pacchetti generati per annotatori/revisori
        returned/            pacchetti completati in attesa di unione
    exports/                 esportazioni CSV dallo stato autorevole
    archive/
        legacy/              artefatti storici, non input attivi senza migrazione esplicita
```

Nel modello previsto, SQLite sarà lo stato operativo autorevole. I CSV saranno
esportazioni e artefatti di audit, non lo stato modificabile primario. La
creazione e l'unione dei pacchetti nel nuovo workflow saranno documentate dopo
la loro implementazione.

## Migrazione validata dello stato esistente

La fonte autorevole delle 401 annotazioni originali è lo snapshot
`annotations/human-train-v0/SensiFake_annotations_401/sensitivity_annotations_401.csv`
(SHA-256 `d4cf41d8df87475321f616dfa09b256513c1ee1f380bb2633a33ac693fa2170b`).
La migrazione richiede percorsi espliciti per questo snapshot e per i tre export
`current`, `confirmed` e `history`. Lo storico è la fonte degli eventi di
revisione; gli altri due export verificano lo stato ricostruito. Le immagini
sono lette tramite i percorsi relativi dello snapshot e le cartelle componenti
del repository. CSV per annotatore possono essere forniti con più opzioni
`--annotator-csv` come controlli aggiuntivi; i loro blind ID sono specifici del
task e possono differire da quelli dello snapshot consolidato.

Per una futura esecuzione, dopo la revisione dello strumento:

```bash
uv run python scripts/tools/migrate_annotations_to_sqlite.py \
  --annotations annotations/human-train-v0/SensiFake_annotations_401/sensitivity_annotations_401.csv \
  --review-current annotations/human-train-v0/sensifake_current.csv \
  --review-confirmed annotations/human-train-v0/sensifake_confirmed.csv \
  --review-history annotations/human-train-v0/sensifake_history.csv \
  --expected-annotations-sha256 d4cf41d8df87475321f616dfa09b256513c1ee1f380bb2633a33ac693fa2170b \
  --report annotations/master/migration-audit.json
```

L'output predefinito è `annotations/master/sensifake.sqlite3`. Se esiste già,
il comando si arresta senza sovrascriverlo. Nessun CSV o file immagine sorgente
viene modificato; il database viene pubblicato solo dopo la validazione.
