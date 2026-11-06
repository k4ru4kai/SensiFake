# Epsilon calibration experiments

These are three historically distinct validation analyses, plus notebook variants
and an original heuristic reference. This directory preserves their scripts and
lightweight recorded outputs. It does not designate a universally optimal epsilon
or a final test result. **No 450-image seed-20 calibration may be transferred to
the 900-image seed-35 test set: the populations overlap by 90 image identities and
use different checkpoints.**

## Motivation and mathematical policy

ADN predicts authenticity; downstream CSN supplies image-only probabilities for
Low, Medium and High sensitivity. The ordinal V3 dataset labeler is a separate
two-threshold model and is not this downstream CSN. Define

`rho = w_L*p_low + w_M*p_medium + w_H*p_high`

and predict Real iff `p_real > 0.5 + epsilon*rho`; ties are Fake. Positive epsilon
raises the evidence required to call an image Real. This can catch more fakes
while increasing false alarms on real images. If probabilities are exact
complements, the equivalent policy is Fake iff `p_fake >= 0.5 - epsilon*rho`.
The scripts check numerical complement errors; they do not silently normalize
saved probabilities or clip thresholds. For nonnegative epsilon and weights,
decisions move from Real to Fake, so missed fakes can decrease while false
alarms increase. This is a deliberate operating-point trade-off, not an
assumption that fusion improves accuracy.

## Common validation population and checkpoint lineage

The input is 450 saved validation rows: 225 Real and 225 Fake, 111 human-labelled
sensitivity targets and 339 automatic silver targets; Low/Medium/High counts are
127/301/22, with 17 true Fake examples in High. Seed 20, run ID
`9415d239074e490fbdedc872be5752ec`, split fingerprint `d936d2726a5dfbc80325cceb1feb6886862f8761c62bbcd08774a47acf5004ec`.

ADN `c956ff778c0eb9ad885d74491ded0b20d322f2e7f003a616152db256e77cfab7`; CSN `93fbd53934482e7fde54f51aece350c9dc2a5e401cea63417987edcc54c68a96`

Original CSV SHA-256: `955dcef2e3553f29db5802997034423632f1ee43fbd55624bdfa22a9783b4aaf`.
The public `inputs/validation_seed20.csv` is a path-sanitized derivative: numeric
strings, labels, row order, identities, run IDs and fingerprints are unchanged;
checkpoint machine paths are portable locators. Its new digest and every
original/candidate pair are in `../../docs/import_catalog.json`. Historical JSON
`validation_input_sha256` fields deliberately retain the original source digest;
they do not claim to hash the sanitized derivative. Recorded paths were changed
only for privacy; all original files remain untouched privately. There is no
re-executed inference proof that these CSV logits came from the checkpoint bytes;
their run/fingerprint metadata agrees. That remaining inference-provenance gap
must not be replaced by a stronger claim.

The evaluation labels and identities match the pinned SensiFake master at
`0804959a6daab0e8041e5120e366580543726905`. This verifies corpus compatibility, not that training recorded this HF
revision: training-time revision fields are missing. Exact executed notebook
bytes are not fully recoverable from the saved hashes. The historical 0.05
summary references notebook hash
`7da80ce63eb1dd812e565de226dc97aad4a2e4366131a070d1f2dc9496491a10`, which differs
from the present notebook variants. Its frozen weight values are retained as
conventions-only AST documents, not invented historical notebooks.

## Strategies and objectives

1. **Fixed historical weights (`scripts/calibrate_fusion.py`).** Weights
   `(0.30,0.50,0.93)`; epsilon grid 0 to 0.5 inclusive, step 0.005 (101 values).
   Require accuracy at least ADN accuracy minus 0.03 and Fake recall at least
   ADN recall. Select maximum Fake recall, maximum macro-F1, minimum regressions,
   then minimum epsilon. Recorded selection: 0.05. Form A (`p_real`) determines
   selection; the alternate `p_fake` form had zero disagreements across the saved
   validation grid. The stale original tools README said validation logits were
   missing; the 450-row export is now available and included here.
2. **Joint weight/epsilon grid (`scripts/calibrate_fusion_weights.py`).** Fix
   `w_H=1`; `w_L=0..0.60` step 0.05; `w_M=0.20..1.00` step 0.05, enforcing
   `w_L <= w_M <= 1`; epsilon 0..0.15 step 0.005. The recorded search tested
   5,735 settings, 2,895 feasible under the same accuracy/recall constraints.
   Selection prioritizes Fake recall, macro-F1, fewer regressions, Fake F1,
   smaller epsilon, proximity to `(1/3,2/3,1)`, then smaller total/individual
   weights. Recorded choice: `(0.45,0.50,1)`, epsilon 0.065. Five-fold
   StratifiedKFold diagnostics use seed 20; they do not select the full-validation
   configuration and are not an independent test. Three distinct configurations
   across five folds and a mean held-out accuracy loss about 0.06222 show that
   calibration constraints do not guarantee held-out fold constraints.
3. **Exact fixed-weight breakpoints (`scripts/calibrate_final_epsilon.py`).**
   Use exact fractions `(1/3,2/3,1)` and saved binary64 probabilities represented
   exactly as rational numbers. There are 202 positive breakpoints, 203 policies
   including zero, and 22 feasible policies. In addition to the same accuracy
   and ordinary recall constraints, require nondecreasing sensitivity-weighted
   Fake recall. True-Fake sensitivity severity units 1/2/3 define that metric;
   predicted CSN probabilities determine prudence, not those severity labels.
   Selection maximizes weighted recall, ordinary recall, macro-F1, then fewer
   regressions, Fake F1, fewer changed predictions and lower exact epsilon.
   The selected decision policy holds on
   **[0.03576980050930068, 0.03908675174646102)**. Exact endpoint fractions are
   `12475616/348775107` and `110919168/2837768887`; decimals are display values.
   Weighted Fake recall is 0.876238 versus the ADN baseline 0.861386. Five-fold
   stability is diagnostic only; one fold selects approximately 0.02505625 and
   four select the reported lower endpoint. No test data selected this interval.

## Verified comparison on this 450-row validation export

FP/FN are counts out of 225 Real / 225 Fake. Macro-F1 and the other metrics are
binary authenticity metrics, not CSN sensitivity classification accuracy.

| Experiment | Weights (L,M,H) / epsilon | Accuracy | Macro-F1 | Fake recall | Fake FNR | FP / FN | Evidence status |
| --- | --- | --- | --- | --- | --- | --- | --- |
| ADN baseline, seed-20 validation | none / 0 | 0.793333 | 0.792792 | 0.844444 | 0.155556 | 58 / 35 | VERIFIED saved arithmetic |
| Historical fixed grid | (0.30,0.50,0.93) / 0.05 | 0.771111 | 0.769195 | 0.862222 | 0.137778 | 72 / 31 | VERIFIED selected policy |
| Joint monotonic-weight grid | (0.45,0.50,1) / 0.065 | 0.766667 | 0.764310 | 0.866667 | 0.133333 | 75 / 30 | VERIFIED selected policy |
| Exact breakpoint calibration | (1/3,2/3,1) / [0.03576980050930068,0.03908675174646102) | 0.771111 | 0.769195 | 0.862222 | 0.137778 | 72 / 31 | VERIFIED exact selected policy |
| Original heuristic reference | (0.30,0.50,0.93) / 0.40 | 0.680000 | 0.649874 | 0.973333 | 0.026667 | 138 / 6 | VERIFIED saved reference; not a selected optimum |

The selected policies were independently evaluated from the saved CSV, without
rerunning the grid searches or resampling diagnostics. The 0.05 and exact
selected policies make identical decisions on these 450 rows (4 corrections and
14 regressions versus ADN); that coincidence does not make their weight vectors
or algorithms equivalent. The joint-grid selection makes 5 corrections and
17 regressions. Its higher recall and lower accuracy reflect the trade-off,
not a superior universal setting. Stability figures remain recorded historical
outputs; their full searches were not rerun for this candidate.

## Weight scale, rounded fractions, and notebook variants

Scaling weights by `c` requires scaling epsilon by `1/c` to preserve thresholds.
Normalizing `(0.30,0.50,0.93)` by 0.93 yields
`(0.3225806452,0.5376344086,1)`, and epsilon 0.05 becomes 0.0465 (0.40 becomes
0.372). This is a scale reparameterization; replacing the weights with
`(0.33,0.66,1)` or `(1/3,2/3,1)` changes their relative contributions and is not
the same operation.

`ProjectSensiFake.ipynb` sets epsilon **0.036**, whereas
`SensiFakeProject-v3.ipynb` sets **0.10**, both with rounded `(0.33,0.66,1)`
and seed 35. They are distinct notebook configurations, not two labels for the
same calibrated result. The 0.036 decimal is within the analytical interval,
but uses different weights and another model pair/split, so this does not verify
it as that run's optimum. The 0.10 variant has no independently verified final
metric attached here. No 0.10 validation/test result was invented or rerun.
Seed-35 saved thresholds are consistent with 0.036/rounded weights within CSV
rounding; their exact source/run linkage is unresolved. Saved notebook outputs
cannot repair this lineage gap. There is **no universally or globally final
epsilon selection verified by this candidate**. The exact interval is verified
only as a selected policy for the stated 450-row validation data and objective.

## Preservation, consolidation and safe reproduction

The four historical script names above identify the inspected `tools/` and
`tools_no/` experiments. Their byte-identical duplicates were consolidated during
preparation; the resulting legacy source is **withheld from v0.1 pending
contributor publication permission**, not offered as runnable release code.
See [deferred source](../../docs/DEFERRED_SOURCE.md). Original scripts and results
remain intact outside this release.

Unique outputs from `formula_test_output`, `tools_no/formula_wigth_test_output`,
and `tools_no/epsilon_final` remain separate under `results/`. Plots show
aggregate experimental results, not dataset examples. The import catalog records
included conversions and digests. Numerical results and calibration algorithms
have not been changed.

From the repository root, supported inexpensive selected-policy verification is:

```bash
python experiments/fusion_calibration/verify_recorded_results.py
python experiments/fusion_calibration/run_analysis.py
python -m pytest -q tests/test_fusion_calibration_release.py
```

Both Python entrypoints verify only the three recorded selected policies using
saved probabilities. They neither repeat searches nor run model inference,
create new results, or alter historical outputs. Full sweeps, training and the
legacy inference exporter are not supported v0.1 entrypoints. Reproducing model
predictions additionally requires permission-cleared source, matched checkpoints
and independently established split provenance.

## Limitations and prohibited comparisons

Validation tuning and its diagnostics are not unbiased test estimates. Most
sensitivity targets here are silver. Twenty-two High validation examples are
small support. The ordinal teacher's training identities also occur in
downstream evaluation. Missing exact training source versions, inconsistent
configuration-source prose and rounded legacy prediction fields constrain
scientific attribution. No source/generator-disjoint or perceptual-duplicate
evaluation has been established. The seed-35 900-row test and seed-20 validation
share **90 identities**; the legacy 900-row test and seed-35 test share 176.
Even zero overlap with a different test population does not prove matching
checkpoints. Do not pool these populations or retrospectively tune the seed-35
test with the seed-20 validation optimum. Any future final test requires one
frozen checkpoint pair, one compatible split, one precise fusion rule and an
independent evaluation population.
