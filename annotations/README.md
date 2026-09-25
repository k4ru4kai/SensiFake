# Annotazioni e risultati

I database e molti risultati sono locali: non vengono scaricati con il clone.
Le cartelle di lavoro vengono create quando necessarie, non sono pacchetti già pronti.

| Percorso | Contenuto |
|---|---|
| `shared/` | Database principale attuale, `sensifake.sqlite3`; percorso mantenuto per compatibilità |
| `offline/<batch>/` | Pacchetti individuali e `assignment.json` creati con `prepare` |
| `returned/<batch>/` | Collocazione consigliata degli snapshot restituiti |
| `exports/<batch>/` | Collocazione consigliata dei CSV scaricati dall’app |
| `openfake/`, `sid-set/`, `human-train-v0/` | Annotazioni precedenti e snapshot esistenti; percorsi preservati |
| `tasks/` | Assegnazioni individuali del workflow precedente |
| `splits/` | Assegnazioni degli split sperimentali |

Lo snapshot SQLite serve a restituire il lavoro; il CSV serve all’analisi.
Per uno snapshot coerente usare il comando `snapshot`, soprattutto quando l’app è aperta.
Non condividere un database in scrittura tra computer tramite cartelle sincronizzate.
Non rinominare o spostare i dati storici per adeguarli a questa mappa.

Istruzioni: [guida offline](../docs/offline_annotation.md).
