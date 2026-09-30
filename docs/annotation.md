# Annotazione e revisione

L'unica applicazione supportata è `scripts/annotation/app.py`.
Il database operativo autorevole è `annotations/master/sensifake.sqlite3`.
Dalla radice del repository:

```bash
uv run streamlit run scripts/annotation/app.py
```

SQLite conserva immagini, provenienza, annotazioni originali e tutte le revisioni.
I CSV sono esportazioni di analisi/audit. Non esiste una dimensione fissa del
progetto, né un numero obbligatorio di immagini o revisori.

## Implementato: passaggio di revisione offline

Il manutentore crea uno snapshot completo e portabile dello stato corrente:

```bash
uv run python scripts/tools/review_snapshots.py create
```

Il comando registra l'emissione nel master e scrive
`annotations/packages/outgoing/review-<id>.sqlite3`. `--master` e
`--output-dir` consentono percorsi espliciti. Non sovrascrive snapshot esistenti.
Lo snapshot contiene tutte le immagini, provenienze, annotazioni e revisioni
preesistenti; le prenotazioni e bozze locali del master non vengono trasferite.
Non è assegnato a una persona: chi lo riceve inserisce la propria identità.

Il collaboratore salva lo snapshot su disco locale e avvia:

```bash
uv run streamlit run scripts/annotation/app.py -- --storage "/percorso/assoluto/review-<id>.sqlite3"
```

L'app riconosce lo snapshot e apre la modalità Review. Inserire sempre lo stesso
nome, scegliere **Resume or reserve an image**, confermare o correggere e premere
**Save review**. L'identità appartiene alla revisione e viene salvata con azione,
motivazione, timestamp e risultato. I nomi sono dichiarati dall'utente, senza
autenticazione: usare la stessa grafia dell'identità originale, senza alias.

È possibile fermarsi dopo qualsiasi numero di revisioni, anche zero. Le revisioni
completate e le bozze inviate all'app restano nel file. Riaprire lo stesso file
con lo stesso nome permette di riprendere; le prenotazioni inattive scadono.
L'app esclude le immagini auto-annotate dalla coda del revisore, lasciandole
pendenti per altre persone. Impedisce anche il salvataggio di un'autorevisione.
Solo le immagini con annotazione originale completata e senza revisioni sono
candidate. Immagini non annotate e immagini già revisionate non entrano nella
coda normale dello snapshot; lo storico multiplo già esistente viene conservato.

Per restituire il lavoro, chiudere Streamlit prima di copiare il file, oppure
creare una copia SQLite coerente usando il comando snapshot già disponibile:

```bash
uv run python scripts/annotation/manage_packages.py snapshot \
  --package "/percorso/assoluto/review-<id>.sqlite3" \
  --output "/percorso/assoluto/review-<id>-returned.sqlite3"
```

Il manutentore conserva il file ricevuto sotto `annotations/packages/returned/`,
lo ispeziona e lo unisce al master:

```bash
uv run python scripts/tools/review_snapshots.py inspect \
  annotations/packages/returned/review-<id>.sqlite3 \
  --master annotations/master/sensifake.sqlite3
uv run python scripts/tools/review_snapshots.py merge \
  annotations/packages/returned/review-<id>.sqlite3
uv run python scripts/tools/review_snapshots.py create
```

La nuova copia può essere consegnata alla stessa persona o a un altro revisore.
Non serve completare lo snapshot. Solo gli eventi di revisione completati vengono
uniti; bozze e prenotazioni del collaboratore restano nel file restituito.
Il collaboratore non modifica direttamente il master. Non scrivere lo stesso
SQLite contemporaneamente attraverso sincronizzazione Dropbox, Drive o Git.

## Identità, validazione e conflitti

Il formato usa lo stesso schema SharedStore, con una tabella `review_snapshot`
contenente versione, UUID dello snapshot, UUID del progetto, data di creazione,
manifest dello stato di partenza e relativo SHA-256. Il manifest include hash
delle immagini, metadati, originali e storico; non duplica i byte delle immagini.
Il master conserva una ricevuta del manifest in `review_issued`, l'identità del
progetto in `review_project` e le identità importate in `review_imports`.
Non eliminare queste tabelle quando si copia o si salva il master.

Ogni nuovo evento è identificato da `(snapshot_id, local_review_id)`; l'ID numerico
locale viene rimappato all'inserimento nel master. Un secondo merge identico non
crea duplicati. Contenuti diversi per la stessa identità causano un conflitto.
Gli ID storici di partenza e tutte le revisioni precedenti sono preservati.

`inspect` senza `--master` verifica solo struttura e coerenza interna. Con il
master verifica anche la ricevuta, l'origine e l'intero piano di merge. I controlli
comprendono schema, integrità SQLite, hash dei byte, originali e provenienza,
identità, divieto di autorevisione, rubriche, motivazioni e ordine temporale.
L'orologio del collaboratore deve essere corretto e i timestamp includere il fuso.
La ricevuta protegge la provenienza dello snapshot; non autentica la persona che
ha dichiarato un nome nell'app.

Uno snapshot vecchio può essere unito se il master ha ricevuto aggiunte o
revisioni su altre immagini. Se entrambi hanno revisionato indipendentemente
la stessa immagine, il merge fallisce interamente, anche con decisioni uguali.
Una prenotazione di revisione attiva sul master è anch'essa un conflitto.
Il comando non sceglie un vincitore né aggiunge una seconda revisione implicita.
Non è prevista adjudication in questa fase. Il piano viene calcolato sotto un
lock di scrittura prima degli inserimenti; gli inserimenti e la validazione
finale sono nella stessa transazione, con rollback su errore.

La creazione pubblica atomicamente il file e registra la ricevuta. Un'interruzione
estrema fra pubblicazione e commit può lasciare un file privo di ricevuta: verrà
rifiutato e deve essere rigenerato. Non ci sono backup automatici accumulati.

## Futuro: aggiunta generica di immagini

La futura operazione attach/import generica non è implementata in questa fase.
Lo schema attuale la supporta già: `images` usa `content_hash` come chiave unica,
`batch_images` conserva appartenenze e provenienza, `annotations` conserva la
prima annotazione e `reviews` gli eventi successivi. Nuove immagini, dataset o
batch arbitrari possono essere aggiunti senza ricostruire il master o cambiare
lo storico. Lo stesso hash non deve creare una seconda identità immagine.

Una fonte può già dichiarare `source_dataset=RRDataset` e una classe real/fake;
questi sono metadati del dataset, non un'annotazione di sensibilità SensiFake.
Senza annotazione originale l'immagine è **unannotated**; dopo annotazione è
**awaiting review**, e solo dopo una revisione è **reviewed**.

I risultati storici restano nei loro percorsi. Non usare annotatori recuperati
dalla cronologia Git. Le utility storiche richieste dall'import iniziale restano
in `scripts/legacy/`. Gli export vanno in `annotations/exports/`; un futuro
archivio potrà usare `annotations/archive/legacy/` senza spostamenti automatici.

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

Comando di migrazione iniziale (non ripetere su un master già esistente):

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
