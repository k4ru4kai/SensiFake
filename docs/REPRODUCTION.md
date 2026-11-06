# Reproduction scope and environments

Supported lightweight operations are pinned HF image resolution and offline
saved-probability arithmetic. `requirements/calibration-observed.txt` records
versions tested in the existing Python 3.12 environment. It is not a freshly
resolved cross-platform lock. The inherited uv.lock/pyproject and benchmark
dependency group are unchanged; the benchmark's NumPy<2 requirement conflicts
with the observed research NumPy 2.5.2 environment. Keep them separate.

`requirements/research-observed.txt` documents the observed research stack,
including CUDA wheel variants. Those wheel variants may need an appropriate
PyTorch wheel index; availability and hardware compatibility have not been
validated in a clean installation. No packages were installed for this candidate.

The new resolver needs Pillow plus Python's standard library. It never writes
the global Hub cache; the master and images are checked by SHA-256. Temporary
job directories hold only recoverable image bytes, never checkpoints or results.
Do not run notebook training cells as a smoke test.

The supported offline suite is `python -m pytest -q` (164 passed, one skip for an
unavailable local-only production fixture after the candidate-only privacy patch).
Six tests cover privacy derivative contracts; restoring the unchanged gold/silver
metadata also enables one previously skipped production-input preservation test.
Two unchanged inherited test files are explicitly archived in `historical_tests/`:
they require persistent images or withheld annotation/assignment fixtures and
produced 18 fixture-related failures in the initial inherited-suite check.
No assertions or calibration algorithms were changed to suppress those failures;
the default pytest testpaths now declares the supported `tests/` scope. The two
archived files are not counted as passing tests.

Newly imported V3 and detector training source and legacy calibration scripts
are withheld pending contributor publication permission; see DEFERRED_SOURCE.md.
The V3 two-output ordinal methodology, historical configurations, checkpoint
fingerprints and saved results remain documented. Full training/inference and
historical grid searches are not supported release entrypoints. The retained
public VLM notebooks are historical evidence, not final scientific authority.
The quickstart notebook demonstrates the supported resolver and offline verifier.
No model weights are distributed.

The benchmark directory is byte-identical to remote main. Its commands assume
external DeepfakeBench dependencies, compatible weights, and local data that
have not been migrated. Its previous 401/2599-image outputs are different
populations from the SensiFake final corpus/test splits. No benchmark run or AUC
repair is claimed by this release integration.
