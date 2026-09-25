# Vecchio annotatore

`annotation_app.py` conserva annotazione su manifest, task individuali e modalità presentazione.
Non condivide automaticamente lo stato con il nuovo annotatore SQLite.

Dalla radice del repository:

```bash
uv run --offline streamlit run annotation_app.py -- --mode annotation --demo
```

Il file nella radice inoltra l’avvio all’implementazione qui conservata.
Anche `uv run --offline streamlit run legacy/annotation_app.py -- --mode annotation --demo` è supportato.
Le [istruzioni originali](ANNOTATION_APP.md) sono conservate; per il nuovo flusso vedere il [README principale](../README.md).
