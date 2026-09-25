# Vecchio annotatore

`scripts/legacy/annotation_app.py` conserva annotazione su manifest, task individuali e modalità presentazione.
Non condivide automaticamente lo stato con il nuovo annotatore SQLite.

Dalla radice del repository:

```bash
uv run --offline streamlit run scripts/legacy/annotation_app.py -- --mode annotation --demo
```

Le [istruzioni originali](ANNOTATION_APP.md) sono conservate; per il nuovo flusso vedere il [README principale](../../README.md).
