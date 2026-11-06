# Run provenance matrix

VERIFIED means artifact bytes, metadata consistency or saved arithmetic were
checked. INFERRED means an explicitly bounded association. UNRESOLVED means
missing/contradictory lineage, not evidence of a final run. None of the rows
proves a fresh training/inference replay. No authority is inferred from a name,
timestamp, maximum metric or saved notebook output.

The pinned corpus is `0804959a6daab0e8041e5120e366580543726905`. VERIFIED: evaluated identities/labels match that
master. UNRESOLVED: training-time HF revision was not recorded. Checkpoint bytes
were hashed and restricted-loaded on CPU for scalar metadata only; no forward
pass occurred. Artifact registry: `../artifacts/checkpoints.json`.

| Artifact/result | Claim status | Seed / split identity | Checkpoint SHA-256 | Decision parameters | Prediction/result population | Unresolved link |
| --- | --- | --- | --- | --- | --- | --- |
| V3 ordinal labeler | VERIFIED checkpoint/config/prediction arithmetic; INFERRED portable source association | seed 42 (configuration); 769/192/140; manifest `11d8d9ad29367340274c576ef317a60be26df611ac516072dff405ecdfc63cf0`; fixed test `d8abc789e35f5b9e0e18e8d6ac56b00b3d6b0564c439cfa582f9c969c2412417` | V3 `48f6495d4a62ded10d98c3835ffcd33c8f5c653e5df19cb03aef62582060e9b4` | Two cumulative outputs; t1=0.50,t2=0.44; no fusion epsilon | results/ordinal_v3/test_predictions.csv; accuracy 0.757143, macro-F1 0.708611 | Exact executed source hash unresolved; recorded notebook hash differs from current portable and original files |
| Legacy detector/fusion test | VERIFIED 900-row arithmetic; INFERRED checkpoint association; UNRESOLVED seed/exact executed notebook | 87b777ac32fff3af233acbb1ce39b1d3958346608cdc683dda8ca44122b9dcd1; legacy seed not established by checkpoint metadata | ADN `e6fc0363bf01097973ee0bd4566c504731a458ac38a1b713c0cebf098a6fff27`; CSN `7a2b5d42c21a794ff3fc9bb974d00121d9e9a2d36b8718bc67bc026613715e9d` | INFERRED saved threshold consistency with (0.30,0.50,0.93), epsilon 0.40 | results/detectors/legacy_test/fusion_predictions.csv; ADN 0.862222, fusion 0.856667; 222 human/678 silver | CSV lacks checkpoint hashes/run ID; no matching training_config.json |
| Seed-35 detector/fusion test | VERIFIED pair metadata + 900-row arithmetic; INFERRED inference association | seed 35 from config/current code; 126e41dbf4a2d2c9868bbdc0d045dfcde3c449cebcdcb291dd31dc6017724e97 | ADN `7e04edd672d7ab67d56ed5fe3594575fecfe654a92b308209619241c91caa6b9`; CSN `c793c62588015cefe4170c92df0b8a19cd8971d9557ac4b2de6d4e86a4711955` | INFERRED threshold consistency with rounded (0.33,0.66,1), epsilon 0.036 within CSV precision | results/detectors/seed35_test/fusion_predictions.csv; ADN 0.815556, CSN sensitivity accuracy 0.831111, fusion 0.813333; 215 human/685 silver | training_config configuration_source names seed-20 validation notebook; current 0.10 variant does not match saved thresholds |
| Seed-20 validation ADN/CSN | VERIFIED CSV and checkpoint run/fingerprint consistency; UNRESOLVED inference replay | seed 20 in matching notebook; d936d2726a5dfbc80325cceb1feb6886862f8761c62bbcd08774a47acf5004ec | ADN `c956ff778c0eb9ad885d74491ded0b20d322f2e7f003a616152db256e77cfab7`; CSN `93fbd53934482e7fde54f51aece350c9dc2a5e401cea63417987edcc54c68a96` | ADN epsilon=0; validation notebook carries unused heuristic epsilon 0.40 | experiments/fusion_calibration/inputs/validation_seed20.csv; ADN 0.793333; 111 human/339 silver | Run 9415d239074e490fbdedc872be5752ec; CSV paths sanitized, original digest documented |
| Historical epsilon 0.05 | VERIFIED saved selected-policy arithmetic; INFERRED producing script version | same 450 seed-20 validation rows / d936d2726a5dfbc80325cceb1feb6886862f8761c62bbcd08774a47acf5004ec | ADN `c956ff778c0eb9ad885d74491ded0b20d322f2e7f003a616152db256e77cfab7`; CSN `93fbd53934482e7fde54f51aece350c9dc2a5e401cea63417987edcc54c68a96` | (0.30,0.50,0.93); epsilon 0.05; maximize Fake recall then macro-F1, fewer regressions, smaller epsilon | historical_fixed_grid/fusion_calibration_validation_summary.json; accuracy 0.771111; Fake recall 0.862222 | Saved source notebook hash 7da80... is not current source; no script hash saved at execution |
| Joint weight/epsilon grid | VERIFIED selected-policy arithmetic; recorded grid/stability not rerun | same 450 seed-20 validation rows / d936d2726a5dfbc80325cceb1feb6886862f8761c62bbcd08774a47acf5004ec | ADN `c956ff778c0eb9ad885d74491ded0b20d322f2e7f003a616152db256e77cfab7`; CSN `93fbd53934482e7fde54f51aece350c9dc2a5e401cea63417987edcc54c68a96` | (0.45,0.50,1); epsilon 0.065; 5735 recorded settings | joint_weight_grid/fusion_weight_calibration_summary.json; accuracy 0.766667; Fake recall 0.866667 | Exact generating source version unresolved; full fold/grid replay deferred |
| Exact-breakpoint calibration | VERIFIED selected exact rational policy; recorded interval table inspected | same 450 seed-20 validation rows / d936d2726a5dfbc80325cceb1feb6886862f8761c62bbcd08774a47acf5004ec | ADN `c956ff778c0eb9ad885d74491ded0b20d322f2e7f003a616152db256e77cfab7`; CSN `93fbd53934482e7fde54f51aece350c9dc2a5e401cea63417987edcc54c68a96` | (1/3,2/3,1); epsilon interval [0.03576980050930068,0.03908675174646102); weighted recall priority | exact_breakpoints/final_epsilon_summary.json; accuracy 0.771111; weighted Fake recall 0.876238 | Optimum scoped to this CSV/objective; cannot transfer to seed-35 test |
| 0.036 and 0.10 notebook variants | VERIFIED current source parameter difference; UNRESOLVED final authority | seed 35 in both; current split 126e41dbf4a2d2c9868bbdc0d045dfcde3c449cebcdcb291dd31dc6017724e97 | Available seed-35 pair above; exact executed-source association unresolved | Rounded (0.33,0.66,1); respectively epsilon 0.036 and 0.10 | notebooks/archive/detectors/ProjectSensiFake.ipynb and SensiFakeProject-v3.ipynb | No independently verified 0.10 performance; 0.036 within exact interval does not validate different rounded weights/models |

## Source version identities

| Source origin | Current full-file SHA-256 | Code-cell SHA-256 | Status |
| --- | --- | --- | --- |
| ComputerVisionProject/ProjectSensiFake.ipynb | ac518470c279d54a6963853ff314439df688630c9f781f4f06459ce09e7069a9 | 2689f5a9283423f058855fb1d62ab8100668cb636b3b6474c5096682e7e5cfcf | VERIFIED current source; not proof of executed training version |
| ComputerVisionProject/SensiFakeProject-v3.ipynb | 812c8257809f0430c3296d85c716b959348fa67136cce34bd596d37a31d63bf5 | f6de912ff399f67948a8dedb6b3a2d85821f8735adc8085fe47b15a63964055e | VERIFIED current source; not proof of executed training version |
| ComputerVisionProject/SensiFakeProject-v3-validation.ipynb | 8994922eb76f24ca8142206c48d4209576e4c33285e074bffc59f1fe596f6eca | 6c3f1d7fff6d3477ffc3acd79dc4e739d4bf20752bfdf287d4f357cd8dc34791 | VERIFIED current source; not proof of executed training version |
| SensiFake-Dataset/model_autoannotator/script/sensitivity_ordinal_v3.ipynb | e47224542a14aa87cec121fbd6ad43aa65d194297abba6359c6a6073e6786db8 | 8d7433066498e5d19b64da8005347e8f7eba6bf5c60a1816233129e14fdaac08 | VERIFIED current source; not proof of executed training version |
| SensiFake/autoannotator-final version/sensitivity_ordinal_v3.ipynb | d951f39f2890b9cd37e5faf0ea16cc0b0232f8d4063881e247fa187873911f5d | 72ee117936ec85808022fb6f1060e4678ade29fa6336d9e38ded4162fc66b3db | VERIFIED current source; not proof of executed training version |

## Prediction file identities before privacy conversion

| Population | Original SHA-256 | Rows | Labels match pinned corpus |
| --- | --- | --- | --- |
| legacy_test | ebf6c7efc481ed0e9da6c20853da67f74e3274b09b427769012d94adcd64d555 | 900 | VERIFIED |
| seed35_test | 89e5561e215d4240271986edb3593c8254dc5a709d1bfcb7a9443b80ac7c94bc | 900 | VERIFIED |
| seed20_validation | 955dcef2e3553f29db5802997034423632f1ee43fbd55624bdfa22a9783b4aaf | 450 | VERIFIED |

Original and candidate hashes for sanitized prediction/config/result files are
in `import_catalog.json`. Calibration result subpaths are relative to
`experiments/fusion_calibration/results/`. Dataset revision association is by
matching image identities/labels, not by fabricated training metadata.

VERIFIED overlaps: seed-20 validation ∩ seed-35 test = 90 identities;
legacy test ∩ seed-35 test = 176; legacy test ∩ seed-20 validation = 0.
Do not use those zero/positive overlaps as a substitute for checkpoint pairing.
No single final detector/fusion run has complete verified provenance.

## Available calibration/export code versions

These current source bytes are VERIFIED equal across tools/ and tools_no/.
Their historical generating execution hashes remain UNRESOLVED because the
original summaries did not record script digests.

| Script | SHA-256 |
| --- | --- |
| calibrate_fusion.py | `c0d6fc67eb0f13764f48eeb475356e66f2c387031675d6c29750dc446f3b3a44` |
| calibrate_fusion_weights.py | `6cd5611005706586505e2377c868840b55f519dca155b22a8a6d2536e895538e` |
| calibrate_final_epsilon.py | `cd5624a75bf1425659bb01c7212ea6f32c753fc901c4c35733e9b1b5008acec9` |
| export_validation_predictions.py | `85c58cfeba667db98428400cafdb146f30e6fe889ceae448c2ad58f0402e4df6` |
