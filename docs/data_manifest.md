# Manifest unico delle selezioni SensiFake

Il manifest è un **file di lavoro del curatore**, non un input dell'interfaccia
di annotazione. Non seleziona il golden set e non assegna score alle immagini
non annotate. Manifest sorgenti, immagini, assegnazioni e CSV umani restano intatti.

## Audit dei file locali

| Fonte | File selezionati | Hash distinti | Classe verificata real / fake / unknown | Annotazioni collegate |
| --- | ---: | ---: | --- | ---: |
| OpenFake | 1.500 | 1.500 | 750 / 750 / 0 | 251 |
| SID-Set | 1.500 | 1.500 | 750 / 750 / 0 | 150 |
| RRDataset | 1.500 | 1.499 | 0 / 0 / 1.500 | 0 |

Tutti i 4.500 file sono leggibili con Pillow. Nei tre manifest OpenFake/SID-Set
gli hash dichiarati coincidono con SHA-256 dei byte. Il duplicato RRDataset è:

- `data/datasets/RRDataset/selection_1500/sara/real/real_008773.jpg`
- `data/datasets/RRDataset/selection_1500/sara/real/real_009566.jpg`
- SHA-256: `4b75a9f3a60308515ce3406ef6ff64bb0acb8b9f50f39259bf036aec7ec79994`

Entrambi i riferimenti restano nel manifest. Non sono due immagini indipendenti.
Non sono emersi altri hash duplicati nelle tre selezioni, né nomi RR ripetuti.

OpenFake è diviso in `data/datasets/openfake/pilot-600/` e `additional-900/`.
SID-Set è in `data/datasets/sid-set/candidate-1500/`. Le classi provengono dai
campi `normalized_label` e `original_label` dei rispettivi `manifest.jsonl`.
Gli adapter in `scripts/collection/source_adapters/` documentano la normalizzazione:
OpenFake conserva real/fake; SID-Set usa 0=real, 1=fake e scarta 2=tampered.
`configs/sources/openfake_additional_900.toml` esclude gli hash già raccolti;
`configs/sources/sid_set_1500.toml` specifica le quote 750/750. Il collector è
`scripts/collection/stream_collect.py`. Non è stato trovato uno script della selezione RR.

OpenFake non ha conservato `sample_id`: l'ID originale resta vuoto, senza
inventarlo a partire dal nome hash. SID-Set conserva 1.500 `sample_id`.
Per RR l'identificativo disponibile è il nome locale del file: non è attestato
come ID ufficiale. L'hash dei byte rimane l'identità verificata per il join.
Il pilot OpenFake non registra `resolved_revision`; additional-900 e SID-Set sì.
Questa limitazione di provenienza è conservata in `source_metadata_json`.

### Prova delle classi RRDataset

La selezione corrente ha 500 file per persona, in `ai` e `real` (250 ciascuna).
Questa organizzazione è successiva al precedente audit della selezione da 300.
La cartella suggerisce 750 fake e 750 real, ma nel repository non è presente
un registro che dimostri da quali cartelle originali siano stati copiati.

Sono stati consultati soltanto metadati e codice ufficiali:

- [README ufficiale al commit a6d1f33](https://github.com/ChunXiaostudy/RRDataset/blob/a6d1f33b5d9a45628d088f9aee5c809d1d529b92/README.md):
  struttura `original/real_images`, `original/ai_images`, oltre a transfer/redigital.
- [Loader ufficiale DRCT](https://github.com/ChunXiaostudy/RRDataset/blob/a6d1f33b5d9a45628d088f9aee5c809d1d529b92/RRBench/Detector%20test%20code/DRCT/test_RRDataset.py):
  `CustomDataset` usa anche cartelle `real` e `ai` con classi 0 e 1.
  Documenta il significato delle cartelle, non la provenienza dei nostri file.
- [Metadati Zenodo](https://zenodo.org/api/records/14963880/files): gli archivi
  ufficiali sono `RRDataset_original_train_val.tar.gz` (2.163.176.547 byte) e
  `RRDataset_test.tar.gz` (20.117.869.400 byte). L'anteprima non espone un indice
  per immagine. I CSV del repository ufficiale riportano metriche aggregate,
  non corrispondenze file/classe. Nessuno dei due archivi è stato scaricato.

Pertanto il manifest registra `normalized_label=unknown`,
`label_verification_status=unverified` e separatamente `label_hint` dalla
cartella locale. **Il prefisso del filename non viene usato per classificare.**
Per verificare le classi servono il registro/script della copia originale,
un indice ufficiale collegabile ai file o un controllo mirato degli originali.

### Le 401 annotazioni

Lo snapshot è
`annotations/human-train-v0/SensiFake_annotations_401/sensitivity_annotations_401.csv`,
SHA-256 `d4cf41d8df87475321f616dfa09b256513c1ee1f380bb2633a33ac693fa2170b`.
Ha 401 hash unici, 401 record validi e 401 join univoci; nessun record è perso.
Conserva 101 `gold_development` e 300 `human_train`, attribuiti a Sara (201),
Giovanni (100) e Lorenzo (100). Ci sono 35 flag `needs_review`.

I campi delle annotazioni, timestamp compresi, coincidono con i quattro CSV
completati originali: OpenFake development (101), `annotation_sara.csv` (100),
`annotation_lorenzo.csv` (100), `annotation-giovanni.csv` (100).
La bozza `annotations/human-train-v0/sara/sensitivity_annotations.csv` ha sette
hash condivisi e sette decisioni discordanti: non è una fonte d'importazione.
Le predizioni Qwen non vengono cercate né importate. Non sono importate nuove
annotazioni dal database dell'app: questo comando riguarda gli export umani
esplicitamente indicati.

## Generazione ripetibile

Dalla radice del repository:

```bash
.venv/bin/python scripts/datasets/build_unified_manifest.py
```

Il comando genera in `data/unified/`:

- `selected_images.csv`: tutte le immagini selezionate e i join sostenuti dai controlli;
- `human_annotations.jsonl`: registro incrementale dei record umani originali;
- `audit_report.json`: conteggi, hash duplicati, classi problematiche, file mancanti,
  ogni esito del join e checksum degli output;
- `.build.lock`: lock per impedire scritture concorrenti della pipeline.

I file dati sono ignorati da Git secondo le regole già presenti. Una seconda
esecuzione con gli stessi input produce gli stessi byte e non riscrive file
identici. Il registro è un'unione di record immutabili: una riga nuova viene
aggiunta, una già importata non è duplicata. Una variante modificata dello
stesso hash è conservata e segnalata come conflitto, senza sovrascrivere la
prima annotazione o scegliere quale decisione usare. Un input successivo che
omette annotazioni già importate non le cancella. Non eliminare il registro
per aggiornare il manifest.

Per aggiungere un altro export umano con lo stesso schema e `annotator_id`:

```bash
.venv/bin/python scripts/datasets/build_unified_manifest.py --annotations /percorso/export_umano.csv
```

`--annotations` è ripetibile; il valore predefinito è esclusivamente lo snapshot
401. Gli export con schema diverso devono essere esaminati prima: il comando
conserva anche record non validi nel registro e li segnala nel report.
Il report elenca gli unmatched e gli ambigui; i valori grezzi completi restano
nel registro. Se un hash identifica più immagini selezionate, lo score non è
assegnato arbitrariamente a una di esse.

### Colonne

`image_id` è SHA-256 di fonte e percorso selezionato: identifica la riga.
`content_hash` è SHA-256 dei byte: identifica il contenuto ed è la chiave di join.
Un trasferimento del file cambia l'ID della riga, ma non l'identità del contenuto.
`declared_content_hash` conserva il valore del manifest sorgente, anche se
l'immagine manca o i byte non coincidono. `original_image_id` e
`original_id_status` distinguono gli ID attestati da quelli non registrati o
disponibili soltanto come filename locale.

La classe operativa è `normalized_label`; `label_evidence_json` conserva i
riferimenti, e `label_verification_status` distingue verified, unverified,
conflict e hash_mismatch. Le classi in conflitto restano unknown.
`source_metadata_json` conserva il record sorgente. I campi umani vengono
copiati come stringhe originali, senza ricalcolare score, confidence o timestamp;
il validatore della rubrica ne controlla la coerenza. Sono conservati anche
`annotator_id`, `dataset_role`, `annotation_source` e `annotation_original_json`.
I campi di sensibilità delle immagini non annotate rimangono vuoti.

Un eventuale CSV `--rr-label-evidence /percorso/prove.csv` deve avere
`content_hash,normalized_label,original_reference,evidence_reference`.
Deve essere costruito dal curatore da metadati autorevoli verificati e collegati
ai byte: non da prefissi o sole cartelle locali ricreate. La pipeline verifica
il collegamento hash e i conflitti; non certifica l'attendibilità di un URL
fornito manualmente. Non è stata prodotta alcuna prova artificiale per RR.

## Cecità e prossima selezione

Il comando non modifica `scripts/legacy/annotation_app.py`, `scripts/annotation/app.py` né i loro
input. L'app condivisa mostra soltanto pixel, ID opaco e campi della rubrica
durante annotazione/review; questo manifest con classi e provenienza rimane
separato ed è riservato al curatore. Non caricarlo come contenuto visibile
nella pagina di annotazione.

Prima di scegliere 300 RRDataset per il golden set occorre verificare le classi
e considerare i due file identici come una sola identità. RRDataset non ha ancora
score umani collegati. La scelta delle 300 RR e delle restanti immagini del set
da 600, la valutazione dei ruoli sperimentali e le nuove annotazioni sono fuori
da questa pipeline: non sono state effettuate.

Test mirati:

```bash
.venv/bin/python -m pytest tests/test_unified_manifest.py -q
```

## Batch RRDataset da 300 immagini per annotazione manuale

La selezione ripetibile è prodotta con:

```bash
.venv/bin/python scripts/datasets/select_rrdataset_batch.py
```

Il criterio è uniforme rispetto ai sei gruppi locali: 50 immagini per ogni
combinazione di `giovanni`, `lorenzo`, `sara` e cartella `real`/`ai`.
Sono quindi 150 immagini per ciascuna classe suggerita dalla cartella, tutte
con hash distinti. I gruppi indicano la provenienza della selezione locale,
non nuovi assegnatari. Non c'è una preferenza per scenari o sensitivity score
presunti. Il seed è 42; l'ordine dipende dall'hash e non dall'ordine dei file.
I duplicati vengono rappresentati da un solo percorso, scelto lessicograficamente,
e tutti gli altri riferimenti restano documentati nel report. Le immagini con
annotazioni già presenti, problemi d'integrità o conflitti sono escluse.

Output in `data/rrdataset-300-v1/`:

- `selected_images.csv`: manifest del curatore con tutte le informazioni originali;
- `selection_report.json`: quote, esclusioni, duplicati e checksum;
- `annotation_batch.zip`: immagini con nomi opachi e metadati di provenienza,
  compatibile con l'importazione nell'app condivisa.

Nell'app scegliere **Import batches**, nome `RRDataset 300 v1`, ruolo `rrdataset`,
e caricare `annotation_batch.zip`. Le etichette operative restano `unknown`;
l'indizio delle cartelle non è trasformato in una classe verificata. I metadati
sono per il curatore e non sono visualizzati durante l'annotazione.
Il batch è una selezione per raccogliere annotazioni: non è ancora un golden
set completo o validato. Non sono assegnati score automaticamente.

La riesecuzione lascia identici gli output. Se gli input o il seed producono
una selezione diversa, il comando rifiuta di sostituirla: usare una nuova
directory `--output` per preservare il batch eventualmente già in annotazione.
Le immagini originali e le 401 annotazioni rimangono intatte.

Lo ZIP corrente pesa circa 257 MiB. `.streamlit/config.toml` imposta il limite
di upload a 350 MiB per consentirne l'importazione; riavviare un'app già avviata
per applicare la configurazione. Il limite interno resta 512 MiB non compressi.
