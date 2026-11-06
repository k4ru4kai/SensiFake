# Scientific issues to resolve

1. **UNRESOLVED final run authority.** Select one source version, checkpoint pair,
   metadata revision, complete ordered split identities and frozen fusion rule.
   Existing source/config/export associations are partial; no final notebook is
   designated here. Source-only candidate copies are explicit derivatives.
2. **VERIFIED cross-run contamination risk.** The 450 seed-20 validation and 900
   seed-35 test sets overlap by 90 content identities; models and split hashes
   differ. Do not retrospectively calibrate that test population. The two old
   test populations share 176 identities and cannot be pooled as independent.
3. **VERIFIED conflicting epsilon/weight definitions.** 0.036 and 0.10 use rounded
   weights; exact 1/3,2/3,1 analysis is a different policy. The 0.05 historical
   selection has historical weights and its own recorded source hash. Keep all
   experiments and scoped objectives; no universal optimum.
4. **VERIFIED metadata conflict.** Seed-35 training_config names the seed-20
   validation notebook as configuration_source. Do not rewrite that original
   artifact to tell a coherent story; establish the actual execution source.
5. **UNRESOLVED execution proof.** CSV run IDs/split fingerprints agree with
   restricted-loaded checkpoints for seed-20. This is metadata consistency, not
   proof of an independently repeated model forward pass. Existing weights are
   preserved privately; source/weight distribution permissions remain unresolved.
6. **VERIFIED label-quality limitation.** Downstream sensitivity targets are mostly
   silver; report human-only sensitivity performance separately. V3 supervision
   identities appear in downstream evaluation. Reusing V3's 140 human test items
   for model comparison limits untouched-test claims; High support is nine.
7. **UNRESOLVED stronger generalization.** Source/generator-disjoint and perceptual
   duplicate controls and a new independent human-labelled test are not established.
8. **UNRESOLVED full reproduction.** V3 local-image preflight and private review
   inputs require adapters; observed research versions are not a solved portable
   lock. Benchmarks require separate dependencies, external weights and data.
   Benchmark AUC tie handling and Effort/Xception naming/population differences
   remain uncorrected historical issues, not silently repaired results.
9. **VERIFIED publication mismatch.** Source/revision/generator rights cannot be
   inferred from the live dataset card. Review OpenFake v1.0 collection terms and
   per-image attribution before endorsing the already published release.

All originals stay intact. No retraining, inference, full calibration search,
result overwrite or retrospective split repair is authorized or performed.
