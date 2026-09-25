# Annotazione offline del batch RRDataset

Il batch `RRDataset-Prova` è stato diviso in tre database indipendenti, con 100
immagini diverse ciascuno. I file si trovano in
`annotations/offline/rrdataset-prova/annotator-01.sqlite3`, `annotator-02.sqlite3`
e `annotator-03.sqlite3`. Il file `assignment.json` nella stessa cartella serve
solo a chi riunirà i risultati: conservarlo insieme al database principale.
`SHA256SUMS.txt` permette di controllare che i tre pacchetti arrivino integri
(`sha256sum -c SHA256SUMS.txt` dalla cartella dei pacchetti).

I nomi non sono preassegnati. Chi riceve un pacchetto inserisce il proprio nome
nell'app; ogni annotazione salvata conserva quel nome. I pacchetti contengono
solo le immagini assegnate, con nomi opachi e senza metadati di provenienza.
Consegnare **un pacchetto diverso a ciascuna persona** con un sistema di
trasferimento file. Non inserire i database nel normale repository Git: i file
sono grandi e ogni salvataggio ne genera una nuova versione completa. GitHub
consiglia di distribuire database grandi tramite un servizio di condivisione
file o come asset di una release.

Finché il nuovo codice non è pubblicato su GitHub, consegnare anche
`offline-app-code.zip` (presente nella stessa cartella). Contiene i file Python
e la configurazione necessari da estrarre nella radice del clone del repository.
Non contiene immagini né annotazioni.

## Istruzioni per chi annota

1. Aggiornare il clone del repository. Se `scripts/annotation/app.py` non è ancora
   presente, estrarre `offline-app-code.zip` nella radice del clone. Installare
   le dipendenze dalla radice del repository con `uv sync`.
2. Salvare il proprio file `annotator-XX.sqlite3` in una cartella locale che
   resterà disponibile anche dopo il riavvio del computer. **Non** aprire lo
   stesso pacchetto contemporaneamente su due computer.
3. Avviare l'app indicando il percorso assoluto del pacchetto:

   ```bash
   uv run streamlit run scripts/annotation/app.py -- --storage /percorso/assoluto/annotator-XX.sqlite3
   ```

4. Nel browser inserire il proprio nome, scegliere **Annotate** e il batch
   **My offline images**, poi usare **Resume or reserve an image**. Dopo ogni
   immagine premere **Save completed annotation**. Usare lo stesso nome quando
   si riprende il lavoro. Le 100 immagini restano nel database locale anche se
   l'app o il computer vengono spenti.
5. Per consegnare il lavoro, salvare l'immagine corrente e creare uno snapshot
   coerente del database:

   ```bash
   uv run python scripts/annotation/manage_packages.py snapshot \
     --package /percorso/assoluto/annotator-XX.sqlite3 \
     --output /percorso/assoluto/annotator-XX-risultati.sqlite3
   ```

   Consegnare il file `annotator-XX-risultati.sqlite3`. Si può fare uno snapshot
   anche prima di completare tutte le 100 immagini; un secondo snapshot con
   ulteriori annotazioni può essere importato più tardi.

## Istruzioni per chi riunisce i risultati

Dal repository che conserva `annotations/shared/sensifake.sqlite3` e
`annotations/offline/rrdataset-prova/assignment.json`, eseguire:

```bash
uv run python scripts/annotation/manage_packages.py merge \
  --master annotations/shared/sensifake.sqlite3 \
  --assignment annotations/offline/rrdataset-prova/assignment.json \
  /percorso/annotator-01-risultati.sqlite3 \
  /percorso/annotator-02-risultati.sqlite3 \
  /percorso/annotator-03-risultati.sqlite3
```

Il comando controlla che ogni immagine appartenga al pacchetto corretto, valida
le annotazioni e importa tutto in una transazione. Ripeterlo con gli stessi file
non crea doppioni; se trova un conflitto, non importa alcuna nuova annotazione.
Si può passare anche un solo file alla volta. Conservare i database originali e
gli snapshot ricevuti fino alla verifica finale dei conteggi.

Per creare una nuova suddivisione da un altro batch interamente non annotato:

```bash
uv run python scripts/annotation/manage_packages.py prepare \
  --master annotations/shared/sensifake.sqlite3 \
  --batch 'NOME DEL BATCH' --parts 3 \
  --output annotations/offline/nuovo-batch
```
