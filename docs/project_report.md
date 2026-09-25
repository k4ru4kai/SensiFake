# SensiFake — Report metodologico sulla creazione del dataset

**Stato del progetto:** dataset sorgente logico di 3.000 immagini completato e validato  
**Data del report:** 28 agosto 2026  
**Repository:** https://github.com/k4ru4kai/SensiFake  
**Dataset pilot pubblicato:** https://www.kaggle.com/datasets/saracristinabasco/sensifake-openfake-pilot

---

## 1. Scopo del documento

Questo report ricostruisce in modo tecnico ma leggibile il processo con cui è stato costruito **SensiFake**, un dataset destinato alla classificazione binaria di immagini **reali** e **sintetiche generate da modelli di intelligenza artificiale**.

L'obiettivo non è soltanto registrare il risultato finale, ma conservare una traccia del ragionamento che ha portato alle scelte metodologiche adottate. Il documento serve quindi come:

1. memoria tecnica del progetto, utile per ripercorrere i passaggi anche a distanza di tempo;
2. base per la futura presentazione dell'esame;
3. documentazione della riproducibilità della raccolta;
4. spiegazione dei concetti informatici utilizzati durante il lavoro, come streaming, hash, manifest, fingerprint, checkpoint e revisioni.

Il progetto è partito da un **pilot di 600 immagini** e si è poi esteso fino a un dataset sorgente logico di **3.000 immagini**, bilanciato in 1.500 reali e 1.500 fake.

---

## 2. Obiettivo complessivo del progetto

L'obiettivo del progetto è costruire un dataset proprio, documentato e verificabile da utilizzare successivamente per addestrare e valutare un classificatore di Computer Vision capace di distinguere:

- immagini reali;
- immagini completamente sintetiche o generate da modelli di AI.

La composizione finale attuale è:

| Componente | Real | Fake | Totale |
|---|---:|---:|---:|
| OpenFake pilot | 300 | 300 | 600 |
| OpenFake additional | 450 | 450 | 900 |
| SID-Set candidate | 750 | 750 | 1.500 |
| **Totale** | **1.500** | **1.500** | **3.000** |

Il dataset finale non è stato duplicato in una quarta cartella contenente copie delle 3.000 immagini. Le tre componenti validate costituiscono il **dataset logico SensiFake da 3.000 immagini**.

Questa scelta evita copie inutili dei dati, riduce il consumo di spazio disco e mantiene chiara la provenienza di ogni componente.

---

## 3. Struttura attuale del dataset

Le tre componenti sono conservate separatamente:

```text
data/datasets/openfake/pilot-600/
data/datasets/openfake/additional-900/
data/datasets/sid-set/candidate-1500/
```

Ognuna contiene immagini e metadati propri.

La separazione è importante perché permette di distinguere:

- la prima raccolta sperimentale da OpenFake;
- l'estensione successiva da OpenFake;
- la componente raccolta da SID-Set.

Durante la validazione finale le tre componenti vengono considerate insieme, ma senza perdere la loro provenienza.

---

## 4. Natura dei dataset sorgente

### 4.1 OpenFake

La prima sorgente utilizzata è **OpenFake**, ospitata su Hugging Face dall'organizzazione `ComplexDataLab`.

Nel progetto è stata utilizzata la revisione richiesta:

```text
v1.0
```

Per la raccolta aggiuntiva da 900 immagini questa revisione è stata risolta in modo esplicito nel commit/digest Hugging Face:

```text
750279a9710d3d98bbc6d0d87250312cfdf922a0
```

Il concetto di "revisione" è importante: un dataset online può cambiare nel tempo. Se ci limitassimo a dire "ho usato OpenFake", una futura esecuzione potrebbe leggere dati diversi. Fissare una revisione permette invece di indicare **quale versione precisa della sorgente** è stata usata.

OpenFake contiene immagini reali e immagini sintetiche generate da numerose famiglie di modelli. Nel pilot sono comparsi, tra gli altri, generatori appartenenti alle famiglie Stable Diffusion, SDXL, Flux, Midjourney, DALL·E, Ideogram, GPT Image e Imagen.

La pipeline normalizza le etichette in due classi semplici:

```text
real
fake
```

Questo significa che, anche se la fonte contiene metadati più specifici sul generatore, per il task principale SensiFake ogni immagine viene ricondotta alla classificazione binaria real/fake.

### 4.2 SID-Set

La seconda sorgente utilizzata è:

```text
saberzl/SID_Set
```

su Hugging Face.

Nel componente SensiFake sono state raccolte:

- 750 immagini reali;
- 750 immagini fake;
- 1.500 immagini totali.

Per la parte fake, i record del manifest mostrano la categoria sorgente:

```text
sid_set_label_name = full_synthetic
```

La revisione richiesta era:

```text
main
```

e la revisione effettivamente risolta durante la raccolta è:

```text
dc03ead57929879319ce30a82bfcfb8d317b10bd
```

Anche in questo caso l'adapter della pipeline converte le etichette specifiche della sorgente nella rappresentazione comune:

```text
normalized_label = real
normalized_label = fake
```

Questa normalizzazione permette di combinare dataset diversi mantenendo un task binario coerente.

### 4.3 Perché usare più di una sorgente

Usare due sorgenti differenti è metodologicamente utile perché riduce il rischio che il modello impari caratteristiche troppo specifiche di un singolo dataset.

Se tutte le immagini provenissero dalla stessa collezione, un classificatore potrebbe sfruttare accidentalmente:

- formati dei file;
- risoluzioni;
- pattern di compressione;
- convenzioni di preprocessing;
- distribuzioni semantiche;
- specifici generatori fake.

L'integrazione di OpenFake e SID-Set non elimina automaticamente questi confondenti, ma rende il dataset più eterogeneo e obbliga a considerarli esplicitamente durante l'analisi.

---

## 5. Strategia generale di raccolta

### 5.1 Perché non è stato scaricato l'intero dataset sorgente

OpenFake e SID-Set sono più grandi del sottoinsieme realmente necessario per il progetto. Scaricare tutto avrebbe avuto diversi svantaggi:

- consumo inutile di spazio disco;
- maggiore traffico di rete;
- più tempo di download;
- difficoltà nel gestire dataset molto grandi localmente;
- nessun vantaggio reale, dato che servivano soltanto 3.000 immagini.

La strategia scelta è stata quindi **leggere i dataset in streaming e salvare soltanto i campioni accettati**.

### 5.2 Che cos'è lo streaming

Con lo streaming il dataset non viene scaricato integralmente prima dell'uso.

In modo semplificato:

```text
dataset remoto
     |
     v
record 1 -> analisi -> accetta/scarta
record 2 -> analisi -> accetta/scarta
record 3 -> analisi -> accetta/scarta
...
```

Il programma riceve progressivamente i record dalla sorgente e decide cosa fare con ciascuno.

Con Hugging Face Datasets questa modalità produce un `IterableDataset`: invece di avere tutte le righe già in memoria, il programma le attraversa tramite un iteratore.

I principali vantaggi sono:

- uso controllato del disco;
- possibilità di interrompersi appena raggiunto il target;
- nessuna necessità di materializzare il dataset completo;
- maggiore scalabilità.

---

## 6. Il problema dello shuffle in streaming

All'inizio si voleva introdurre casualità attraverso lo shuffle dello stream.

Questo ha mostrato un problema importante.

Uno shuffle tradizionale su un array può mescolare gli indici. In streaming, invece, non abbiamo davanti l'intero dataset. Hugging Face utilizza quindi un **buffer**: conserva temporaneamente un certo numero di record e ne estrae uno casualmente alla volta.

Per record testuali leggeri questo è ragionevole. Nel nostro caso, però, un record può contenere i byte di un'immagine ad alta risoluzione.

Quindi:

```text
buffer da 2.000 record
```

non significava "2.000 piccole righe di metadati", ma potenzialmente migliaia di immagini residenti in memoria.

### Test effettuati

Sono stati provati buffer di:

- 2.000 record;
- 50 record;
- 5 record.

Anche buffer molto piccoli hanno provocato una crescita della memoria incompatibile con l'ambiente disponibile.

Il primo smoke test ha raggiunto circa 1,53 GiB prima di essere terminato; altri test hanno superato circa 3 GiB.

### Decisione finale

Lo shuffle dei payload è stato disabilitato.

La sorgente viene letta **sequenzialmente**, mentre la randomizzazione viene rimandata a una fase successiva, dove può avvenire sugli indici o sui metadati invece che sui byte delle immagini.

Questa è una scelta importante da ricordare:

> SensiFake è bilanciato per classe, ma la raccolta sorgente non costituisce un campionamento casuale globale dell'intero dataset remoto.

---

## 7. Pipeline di raccolta

La logica principale è implementata in:

```text
scripts/collection/stream_collect.py
```

e viene controllata tramite configurazioni TOML.

Per ogni record, la pipeline esegue concettualmente questi passaggi:

1. riceve il record dallo stream;
2. legge la label originale;
3. converte la label nella classe comune `real` o `fake`;
4. controlla se la quota della classe è già piena;
5. recupera i byte originali dell'immagine;
6. calcola l'hash SHA-256;
7. controlla se lo stesso hash è già presente;
8. controlla se l'hash appartiene a dataset che devono essere esclusi;
9. legge formato, dimensioni e modalità colore;
10. salva l'immagine;
11. scrive i metadati nel manifest;
12. aggiorna contatori e checkpoint;
13. continua fino al raggiungimento delle quote.

---

## 8. Concetti teorici usati nella pipeline

Questa sezione raccoglie i concetti che sono stati utilizzati tecnicamente nel progetto e che è utile saper spiegare.

### 8.1 Hash

Un **hash** è una stringa calcolata a partire dal contenuto di un file tramite una funzione matematica.

Nel progetto viene utilizzato **SHA-256**.

Esempio:

```text
d931f69279a1ce072f0cb8b4090b93d1843a8f74f7dbb68c66e4ea7577c7100e
```

Quella stringa rappresenta il contenuto dell'immagine.

Proprietà fondamentali:

- lo stesso contenuto produce lo stesso hash;
- modificare anche un singolo byte produce, con probabilità estremamente alta, un hash diverso;
- non è pratico ricostruire il file originale partendo dall'hash;
- due contenuti differenti hanno una probabilità trascurabile di produrre lo stesso SHA-256.

Nel progetto gli hash servono soprattutto per **deduplicare**.

Esempio:

```text
foto_A.jpg -> SHA256 = ABC123...
foto_B.jpg -> SHA256 = ABC123...
```

Anche se i nomi sono diversi, se i byte sono identici i due file producono lo stesso hash. La pipeline riconosce quindi che sono duplicati.

Importante: questa deduplicazione trova duplicati **byte-identici**. Due immagini visivamente identiche ma ricompresse, ridimensionate o ricodificate possono avere hash diversi.

### 8.2 Fingerprint

Un **fingerprint** è, in pratica, un hash usato come impronta di una struttura più grande: per esempio una cartella, un insieme di file o una configurazione.

Nel progetto sono stati utilizzati due tipi di fingerprint.

#### Fingerprint dei dati

Serve a verificare che una directory non sia cambiata.

Esempio:

```text
OpenFake pilot fingerprint
42f5a256996458bb226b162264bfaa5bda0f3ba2712fb74ac58b24a05dcc6a6f
```

Se uno dei file protetti cambiasse, il fingerprint finale sarebbe differente.

#### Source fingerprint

Il collector calcola anche un'impronta della configurazione critica della sorgente.

Per `additional-900`:

```text
d8a4d72aaef623f72fe7c4ae1a499fe0218a1d3c7ed98a50be3bc63778397995
```

Questo permette di verificare che un eventuale resume venga eseguito con la stessa sorgente, configurazione ed exclusion set del run originario.

### 8.3 Manifest

Un **manifest** è un file che descrive sistematicamente tutti gli elementi di un dataset.

Nel progetto viene usato:

```text
manifest.jsonl
```

JSONL significa "JSON Lines": ogni riga contiene un oggetto JSON indipendente.

Un record tipico può contenere:

```text
content_hash
normalized_label
relative_image_path
source_dataset
requested_revision
resolved_revision
width
height
image_format
byte_source
```

Il manifest permette quindi di sapere non soltanto che un'immagine esiste, ma:

- da dove proviene;
- quale etichetta ha;
- quale hash possiede;
- dove si trova;
- con quale revisione della sorgente è stata raccolta.

### 8.4 Checkpoint

Un **checkpoint** è uno stato intermedio salvato durante un processo lungo.

Nel nostro caso `checkpoint.json` conserva informazioni come:

```text
scanned
accepted
accepted_by_label
excluded
duplicates
errors
```

Se il collector viene interrotto, il checkpoint permette di sapere a che punto era arrivato e, quando previsto, di riprendere senza ricominciare da zero.

### 8.5 Summary

`summary.json` descrive lo stato conclusivo del run.

Contiene:

- motivo di terminazione;
- contatori finali;
- sorgente;
- revisione;
- quote;
- informazioni sulle exclusion.

Il checkpoint rappresenta quindi principalmente lo **stato operativo**, mentre il summary rappresenta il **riepilogo del run**.

### 8.6 Revisione

Una revisione identifica una versione precisa della sorgente.

Esempio:

```text
requested_revision = v1.0
resolved_revision = 750279a...
```

`v1.0` è il nome leggibile richiesto; il secondo valore identifica lo snapshot concreto risolto dalla piattaforma.

Questo concetto è analogo a un commit Git: serve a rendere l'esperimento riproducibile nel tempo.

### 8.7 Parquet

Hugging Face memorizza molti dataset in file **Parquet**.

Parquet è un formato tabellare colonnare, pensato per l'elaborazione efficiente di grandi quantità di dati.

Il nostro collector non deve gestire manualmente i file Parquet: Hugging Face Datasets e PyArrow si occupano della lettura. Tuttavia il comportamento di PyArrow è stato rilevante nei problemi di memoria e shutdown osservati durante il progetto.

### 8.8 Byte originali e ricodifica

Quando un'immagine viene aperta e poi salvata nuovamente, può essere **ricodificata**.

Per esempio, aprire un JPEG con Pillow e risalvarlo potrebbe modificare:

- compressione;
- metadati;
- quantizzazione;
- byte del file.

Poiché SensiFake può essere usato anche per studiare segnali forensi, si è scelto di preservare, quando possibile, il file originale esattamente come ricevuto.

Il manifest registra:

```text
byte_source = original_encoded_bytes
```

Nel dataset finale OpenFake aggiuntivo tutte le 900 immagini sono state conservate in questo modo e il numero di re-encode è zero.

### 8.9 RSS e memoria

Nei log viene spesso indicata la **RSS**, Resident Set Size.

È una misura approssimativa della quantità di memoria RAM realmente residente utilizzata dal processo.

Per la raccolta `additional-900` il picco misurato è stato:

```text
1.702.264 KiB
```

circa 1,62 GiB.

Questa misura è stata utile soprattutto durante la diagnosi dello shuffle.

### 8.10 Exit code

Quando un programma termina restituisce un codice numerico.

Esempi osservati nel progetto:

- `0`: terminazione normale;
- `137`: processo terminato da SIGKILL, spesso osservato quando viene ucciso per uso eccessivo di risorse;
- `134`: tipicamente associato a `SIGABRT`, cioè un abort del runtime nativo.

L'exit code da solo non dice sempre se i dati sono validi. Per questo il progetto non si affida soltanto al codice di uscita, ma esegue controlli indipendenti sui file prodotti.

---

## 9. Deduplicazione

La deduplicazione è uno degli aspetti centrali del dataset.

### 9.1 Deduplicazione interna

Ogni nuovo campione viene confrontato con gli hash già accettati nello stesso run.

Se l'hash è già presente:

```text
duplicates += 1
```

e l'immagine non viene aggiunta nuovamente.

Nella raccolta `additional-900` sono stati rilevati:

```text
2 duplicati
```

che non sono stati conteggiati nelle quote.

### 9.2 Deduplicazione tra componenti

Per l'estensione OpenFake non bastava evitare duplicati all'interno del nuovo run.

Era necessario assicurarsi che le 900 nuove immagini non fossero già presenti:

- nel pilot OpenFake da 600;
- nel candidate SID-Set da 1.500.

Sono stati quindi utilizzati **exclusion manifest**.

Gli hash esclusi erano:

```text
600 dal pilot OpenFake
1500 dal SID-Set
2100 hash unici totali
```

Prima della raccolta è stato verificato che pilot e SID-Set non avessero hash in comune.

Durante il nuovo scan, ogni hash appartenente all'exclusion set veniva scartato.

Questo è il motivo per cui il run `additional-900` ha registrato:

```text
excluded = 600
excluded_existing_hash = 600
```

Dato che OpenFake veniva letto sequenzialmente dalla stessa sorgente usata per il pilot, il collector ha incontrato nuovamente immagini già presenti e le ha correttamente ignorate.

---

## 10. Raccolta del pilot OpenFake da 600 immagini

Il pilot è stato la prima prova completa della pipeline.

Configurazione:

- 300 real;
- 300 fake;
- 600 totali;
- streaming sequenziale;
- shuffle disabilitato;
- checkpoint periodico;
- preservazione dei byte originali.

Risultato:

| Metrica | Valore |
|---|---:|
| Record scansionati | 611 |
| Immagini accettate | 600 |
| Real | 300 |
| Fake | 300 |
| Skipped | 11 |
| Duplicati | 0 |
| Errori | 0 |
| Re-encode | 0 |
| Exit reason | `target_reached` |
| Exit code | 0 |
| Durata | 11 min 28,33 s |
| Output | 315,1 MiB |

Il pilot ha permesso di scoprire e correggere i principali problemi della pipeline prima di scalare la raccolta.

Il codice della prima pipeline riproducibile è stato versionato nel commit:

```text
14c4e176c4a7396f96ebc8ef411c164cf0cf1575
feat: add reproducible SensiFake pilot collection pipeline
```

---

## 11. Raccolta SID-Set da 1.500 immagini

La seconda grande componente è stata costruita da `saberzl/SID_Set`.

Il risultato finale validato è:

| Classe | Numero |
|---|---:|
| Real | 750 |
| Fake | 750 |
| Totale | 1.500 |

Gli hash sono tutti unici all'interno della componente.

La validazione ha confermato:

- 1.500 righe di manifest;
- 1.500 file immagine;
- 1.500 hash unici;
- zero file mancanti;
- zero file extra;
- zero hash mismatch;
- zero decode failure;
- zero path escape;
- coerenza tra percorso ed etichetta.

Questa componente è stata poi congelata come input protetto prima della raccolta OpenFake aggiuntiva.

---

## 12. Raccolta OpenFake aggiuntiva da 900 immagini

### 12.1 Obiettivo

L'obiettivo era ottenere:

```text
450 real nuove
450 fake nuove
900 immagini totali
```

senza sovrapporsi alle 2.100 immagini già presenti nel pilot e nel SID-Set.

### 12.2 Sorgente

```text
dataset: ComplexDataLab/OpenFake
split: train
requested revision: v1.0
resolved revision: 750279a9710d3d98bbc6d0d87250312cfdf922a0
```

### 12.3 Exclusion manifest

Prima del run sono stati registrati due manifest da escludere:

```text
pilot-600: 600 hash
SID-Set: 1500 hash
totale: 2100 hash unici
```

I loro digest SHA-256 erano:

```text
pilot manifest
fee334c22c5c6cae96e0cc4b74db1a28d6b8ac93fd7605850d57d41466578743

SID manifest
9416fc6370ec6582eff21826815ede07369c62eaecce04f2d36b3992dfc930bf
```

### 12.4 Risultato finale

Il checkpoint finale contiene:

```text
scanned = 1509
accepted = 900
real = 450
fake = 450
excluded = 600
duplicates = 2
skipped = 7
errors = 0
reencoded_fallbacks = 0
```

I 7 record skipped erano:

```text
quota_fake_reached = 7
```

Significa che la quota fake era già completa e il collector ha continuato a leggere finché non è stata completata anche la quota real.

L'equazione dei contatori è coerente:

```text
600 excluded
+ 900 accepted
+ 2 duplicates
+ 7 skipped
= 1509 scanned
```

Questo è un controllo semplice ma importante, perché dimostra che ogni record scansionato è spiegato da una categoria del collector.

### 12.5 Risorse

La raccolta ha impiegato:

```text
3 h 16 min 50 s
```

Picco RSS:

```text
1.702.264 KiB ≈ 1,62 GiB
```

Dimensioni rilevate:

- output: circa 458 MiB;
- cache isolata: circa 68 KiB;
- log: circa 324 KiB.

---

## 13. Anomalia finale: exit code 134

La raccolta `additional-900` ha raggiunto correttamente:

```text
exit_reason = target_reached
```

e ha scritto un checkpoint e un summary coerenti.

Subito dopo il completamento è però comparso:

```text
terminate called without an active exception
```

e il processo esterno `/usr/bin/time` ha registrato:

```text
Exit status: 134
```

Questo codice è compatibile con un `SIGABRT` proveniente dal runtime nativo C/C++.

La parte importante è l'ordine degli eventi:

1. il target di 900 immagini era già stato raggiunto;
2. checkpoint e summary erano già stati persistiti;
3. il processo ha abortito durante o immediatamente dopo il teardown;
4. non è stato registrato nessun errore di raccolta;
5. la validazione indipendente successiva ha confermato la completa integrità dei dati.

Per questo motivo **non è stato eseguito un resume** e non è stata rifatta la raccolta.

La causa precisa del teardown non è stata dimostrata con uno stack trace nativo. Il comportamento è compatibile con i precedenti problemi osservati nell'interazione tra Hugging Face Datasets, PyArrow e la finalizzazione dello stream, ma questa attribuzione va considerata una diagnosi plausibile e non una prova definitiva.

---

## 14. Problemi tecnici incontrati e soluzioni

### 14.1 Shuffle e memoria

Problema:
- buffering di record immagine troppo pesante;
- crescita eccessiva della RAM;
- exit 137 nei test.

Soluzione:
- shuffle sorgente disabilitato;
- scansione sequenziale;
- eventuale randomizzazione spostata sui metadati.

### 14.2 Shutdown di PyArrow / Hugging Face Datasets

Durante i test preliminari si erano osservati crash durante la finalizzazione Python.

Messaggi registrati includevano:

```text
Fatal Python error: PyGILState_Release
Python runtime state: finalizing
```

Sono stati testati diversi tentativi di cleanup.

La configurazione più stabile è stata ottenuta usando:

```python
batch_size = 1
ParquetFragmentScanOptions(pre_buffer=False)
```

insieme a una gestione esplicita dell'ordine di chiusura degli iteratori.

Questa soluzione aveva superato dieci processi target-1 consecutivi ed era stata sufficiente per il pilot da 600 immagini.

Il successivo exit 134 dopo il completamento del run da 900 dimostra però che il teardown nativo resta un comportamento da documentare e monitorare nelle esecuzioni future.

### 14.3 Signal handling

Il collector gestisce SIGINT e SIGTERM in modo ordinato.

Se fosse stato necessario interrompere una raccolta, la procedura prevista era:

- inviare un singolo SIGINT;
- attendere il salvataggio del checkpoint;
- lasciare terminare il cleanup;
- evitare SIGKILL salvo emergenza.

### 14.4 Pubblicazione Kaggle

Il pilot è stato pubblicato manualmente su Kaggle.

Questa esperienza ha mostrato una distinzione utile:

- automazione e agenti sono molto utili per operazioni ripetibili, test e verifiche;
- per alcune operazioni esterne una tantum collegate a un account personale, l'azione manuale può essere più veloce, comprensibile e controllabile.

---

## 15. Validazione di `additional-900`

Dopo la raccolta è stato eseguito un validator indipendente.

Risultati:

```text
manifest_records = 900
filesystem_image_files = 900
labels = 450 real + 450 fake
unique_hashes = 900
path_escapes = 0
label_path_mismatches = 0
missing_manifest_paths = 0
extra_image_files = 0
hash_mismatches = 0
decode_failures = 0
```

Inoltre:

```text
byte_sources = original_encoded_bytes per tutte le 900 immagini
```

Le revisioni registrate sono tutte coerenti:

```text
requested_revision = v1.0
resolved_revision = 750279a9710d3d98bbc6d0d87250312cfdf922a0
source_dataset = ComplexDataLab/OpenFake
split = train
```

`summary.json` e `checkpoint.json` hanno gli stessi contatori.

---

## 16. Validazione globale delle 3.000 immagini

La validazione finale non si è limitata a fidarsi dei manifest.

Gli hash sono stati **ricalcolati direttamente dai byte delle immagini presenti su disco**.

Questo è importante: se un file fosse stato accidentalmente sostituito, il manifest potrebbe ancora contenere il vecchio hash, ma il confronto con i byte reali rileverebbe il problema.

### Risultato per componente

#### OpenFake pilot

```text
600 manifest records
600 image files
300 real
300 fake
600 unique hashes
0 missing
0 extra
0 hash mismatch
0 decode failures
```

#### OpenFake additional

```text
900 manifest records
900 image files
450 real
450 fake
900 unique hashes
0 missing
0 extra
0 hash mismatch
0 decode failures
```

#### SID-Set

```text
1500 manifest records
1500 image files
750 real
750 fake
1500 unique hashes
0 missing
0 extra
0 hash mismatch
0 decode failures
```

### Intersezioni tra componenti

Sono state calcolate le intersezioni tra gli insiemi di hash:

```text
pilot ∩ additional = 0
pilot ∩ SID = 0
additional ∩ SID = 0
```

Quindi nessuna immagine byte-identica compare in due componenti diverse.

### Risultato globale

```text
3000 manifest records
3000 image files
1500 real
1500 fake
3000 globally unique hashes
0 label conflicts
0 missing files
0 extra files
0 hash mismatches
0 decode failures
```

Questo è il risultato principale della fase di raccolta:

> SensiFake contiene 3.000 immagini sorgente bilanciate e globalmente deduplicate per SHA-256.

---

## 17. Annotazioni di sensibilità

Il progetto include anche:

```text
annotations/openfake/development-v0/sensitivity_annotations.csv
```

Al momento della validazione globale erano presenti:

```text
101 annotation rows
101 unique annotation hashes
0 duplicate annotation hashes
0 annotation hashes missing from pilot
```

Quindi tutte le annotazioni continuano a riferirsi a immagini valide del pilot OpenFake.

Questo è importante perché il collegamento non dipende dal nome o dall'ordine delle immagini, ma dal loro `content_hash`.

Se la struttura delle cartelle cambiasse, l'hash continuerebbe comunque a identificare lo stesso contenuto.

---

## 18. Controlli di integrità tramite fingerprint

Prima della raccolta aggiuntiva alcuni componenti sono stati dichiarati "protetti".

Dopo il run sono stati ricalcolati gli stessi fingerprint per verificare che non fossero stati modificati.

Risultati finali:

```text
OpenFake pilot
42f5a256996458bb226b162264bfaa5bda0f3ba2712fb74ac58b24a05dcc6a6f

OpenFake annotations
c783a28509ca200d37d7b9e0f79a4bdd359c3f59f16acf2a0a80759875eb573f

SID-Set candidate
c7c382c323c90b6e41ea91e5f6910ab99a17c6e1d1e857f6973408994eef6073

SID schema probe
f54d4731af23fea448dfe65d3684887e47b67fdaeee6431568d709a37dc9d64a

SID revision check
6e0077f4811dc4e42265d4afe503b1bff2e99b15902b310610681c7847f1155d
```

Tutti coincidono con i valori attesi.

Il fingerprint finale della nuova componente `additional-900` è:

```text
78f06835e4f1358371802b26c8895dec0b19015c034b80a179a30e71372a324c
```

### Nota sui symlink

Durante il controllo dei fingerprint è emersa una differenza tra "file regolare" e "symlink".

Un **symlink** è un collegamento simbolico: non contiene necessariamente una copia del file, ma punta a un altro percorso.

Hugging Face utilizza symlink nelle cache.

Il primo validator Python seguiva questi collegamenti e contava un file in più in alcune directory. Il metodo storico usato per i fingerprint considerava invece soltanto i file regolari tramite:

```text
find ... -type f
```

Usando lo stesso metodo originale, i fingerprint sono risultati corretti.

Questa è una lezione metodologica importante: un fingerprint è confrontabile soltanto se viene calcolato **con lo stesso algoritmo e le stesse regole**.

---

## 19. Test del codice e stato Git

Dopo la raccolta sono stati eseguiti:

### Focused tests

```text
16 passed
```

### Suite completa

```text
60 passed
```

### Ruff

```text
All checks passed
```

### Git diff check

```text
git diff --check
```

superato senza errori.

Il commit finale della logica di estensione OpenFake è:

```text
103a0b4f7009925fc8ebe9b5806c8d246f493c78
feat: add deduplicated OpenFake extension collection
```

Local `main` e `origin/main` puntano allo stesso commit.

Lo stato Git finale è:

```text
## main...origin/main
 M uv.lock
```

`uv.lock` è l'unica modifica locale preesistente.

Il suo SHA-256 è rimasto:

```text
87a9d8b85d03b4d402c033c4092a9d1dff32e625fe72ba88ce7ff5706a723f30
```

Nessun dataset, immagine, cache o log generato è stato aggiunto a Git.

---

## 20. Strumenti e tecnologie utilizzati

| Componente | Versione/ruolo | Utilizzo |
|---|---:|---|
| Python | 3.12.13 | Collector, validazione, hashing, metadati |
| Hugging Face Datasets | 5.0.1 | Streaming dei dataset |
| PyArrow | 25.0.1 | Lettura dei Parquet |
| Pillow | 12.3.0 | Decodifica e verifica immagini |
| tqdm | 4.70.0 | Progress bar |
| uv | 0.11.29 | Ambiente e dipendenze |
| pytest | 9.1.1 | Test automatici |
| Ruff | 0.16.4 | Linting e controlli statici |
| TOML | configurazione | Parametri del collector |
| JSON / JSONL | metadati | Manifest, checkpoint, summary |
| Git / GitHub | versionamento | Codice e configurazioni |
| Kaggle | storage/pubblicazione | Pilot pubblicato manualmente |

---

## 21. Riproducibilità

Il progetto prova a separare chiaramente:

### Codice

Conservato in GitHub.

Comprende:

- collector;
- adapter delle sorgenti;
- configurazioni;
- test;
- logica di deduplicazione;
- logica di revision pinning.

### Dati runtime

Non versionati con Git.

Comprendono:

- immagini;
- manifest;
- checkpoint;
- summary;
- cache;
- log.

### Ambiente Python

Gestito con:

```text
.python-version
pyproject.toml
uv.lock
```

L'uso di `uv run --frozen` impedisce di modificare implicitamente le dipendenze durante le verifiche.

---

## 22. Punti di forza metodologici

1. **Dataset proprio ma con provenienza tracciata.**  
   Le immagini vengono selezionate e ricomposte in un dataset nuovo, ma la fonte originale resta registrata.

2. **Version pinning.**  
   Le revisioni delle sorgenti sono registrate e validate.

3. **Streaming.**  
   Non è necessario scaricare interamente dataset molto grandi.

4. **Bilanciamento esplicito.**  
   Il dataset finale contiene esattamente 1.500 real e 1.500 fake.

5. **Deduplicazione interna e globale.**  
   Sono stati verificati 3.000 SHA-256 globalmente unici.

6. **Preservazione dei byte originali.**  
   Il collector non introduce inutilmente nuove compressioni.

7. **Manifest dettagliati.**  
   Ogni immagine è accompagnata da provenienza e metadati.

8. **Checkpoint e resume.**  
   Le raccolte lunghe possono essere recuperabili dopo un'interruzione.

9. **Validazione indipendente.**  
   Non ci si limita a fidarsi del collector: hash e file vengono ricontrollati dopo il run.

10. **Componenti protetti tramite fingerprint.**  
    È possibile dimostrare che i dataset precedenti non sono stati alterati.

11. **Separazione dati/codice.**  
    Il repository non viene appesantito dalle immagini runtime.

---

## 23. Limiti metodologici ancora presenti

### 23.1 Campionamento sequenziale

La raccolta non è una selezione casuale globale.

Questo può introdurre bias legati all'ordine della sorgente.

### 23.2 Hash esatto non significa similarità visiva

SHA-256 rileva duplicati byte-identici.

Non rileva automaticamente:

- stessa immagine ricompressa;
- crop della stessa immagine;
- resize;
- lievi modifiche;
- copie con metadati diversi.

Per il futuro potrebbe essere utile introdurre tecniche di **near-duplicate detection**, ad esempio perceptual hashing o embedding visivi.

### 23.3 Confondenti tecnici

Il classificatore potrebbe sfruttare segnali come:

- formato JPEG/PNG/WEBP;
- risoluzione;
- aspect ratio;
- compressione;
- provenienza del dataset;
- generatori maggiormente rappresentati.

Questi aspetti dovranno essere misurati prima del training definitivo.

### 23.4 Distribuzione dei generatori

La classe fake non è necessariamente uniforme tra generatori.

Un modello potrebbe quindi diventare molto bravo su alcuni generatori e meno generalizzabile su altri.

### 23.5 Split non ancora definitivi

Il dataset sorgente da 3.000 immagini è validato, ma train/validation/test devono ancora essere progettati con attenzione.

La divisione dovrà evitare leakage e, quando possibile, essere stratificata anche rispetto a sorgente e generatori.

---

## 24. Stato corrente del progetto

Alla data del 28 agosto 2026:

- il pilot OpenFake da 600 immagini è completato;
- SID-Set candidate da 1.500 immagini è completato;
- l'estensione OpenFake da 900 immagini è completata;
- tutte le tre componenti sono validate;
- il dataset logico contiene 3.000 immagini;
- il bilanciamento è 1.500 real / 1.500 fake;
- tutti i 3.000 hash sono globalmente unici;
- non esistono overlap tra le tre componenti;
- tutte le immagini decodificano correttamente;
- non sono stati osservati hash mismatch;
- le 101 annotazioni di sensibilità restano valide;
- test e lint del repository passano;
- le componenti protette mantengono i fingerprint attesi;
- nessun dataset runtime è tracciato da Git.

La fase di **raccolta e validazione del source dataset da 3.000 immagini può quindi essere considerata completata**.

---

## 25. Prossimi step

Il prossimo lavoro non consiste più nel raccogliere immagini, ma nel trasformare il dataset sorgente validato in un dataset sperimentale adatto al training.

I passaggi consigliati sono:

1. analizzare la distribuzione di formati, risoluzioni e aspect ratio sulle 3.000 immagini;
2. analizzare la distribuzione dei generatori fake;
3. valutare eventuali near-duplicate non rilevabili con SHA-256;
4. definire train, validation e test in modo deterministico;
5. evitare leakage tra split;
6. decidere se stratificare anche per sorgente e generatore;
7. preparare un notebook conforme alle linee guida del corso;
8. implementare un baseline semplice;
9. misurare accuracy, precision, recall, F1 e confusion matrix;
10. confrontare il baseline con un modello più avanzato;
11. integrare l'analisi di sensibilità nel progetto;
12. aggiornare README, report e presentazione con risultati sperimentali.

---

## 26. Riferimenti principali

- Repository SensiFake: https://github.com/k4ru4kai/SensiFake
- Pilot Kaggle: https://www.kaggle.com/datasets/saracristinabasco/sensifake-openfake-pilot
- OpenFake: https://huggingface.co/datasets/ComplexDataLab/OpenFake
- OpenFake paper: https://arxiv.org/abs/2509.09495
- Hugging Face streaming documentation: https://huggingface.co/docs/datasets/main/stream
- Hugging Face Datasets issue #7357: https://github.com/huggingface/datasets/issues/7357
- Apache Arrow issue #45214: https://github.com/apache/arrow/issues/45214
- Apache Arrow issue #49942: https://github.com/apache/arrow/issues/49942

---

## 27. Sintesi finale

La parte più importante del lavoro svolto non è stata semplicemente "scaricare 3.000 immagini".

È stata costruita una pipeline controllata che:

- legge grandi dataset senza doverli scaricare interamente;
- mantiene la provenienza dei campioni;
- conserva i byte originali;
- identifica le immagini tramite SHA-256;
- elimina duplicati interni e tra sorgenti;
- protegge raccolte precedenti tramite exclusion manifest;
- salva checkpoint e summary;
- registra le revisioni delle sorgenti;
- permette di verificare a posteriori ogni file;
- controlla che i dataset precedenti non siano stati modificati;
- produce un dataset finale bilanciato e globalmente deduplicato.

Il risultato attuale è quindi un **source dataset SensiFake di 3.000 immagini, 1.500 real e 1.500 fake, validato a livello di file, hash, manifest e provenienza**.

Il passo successivo è passare dalla **costruzione del dataset** alla **progettazione dell'esperimento di classificazione**.
