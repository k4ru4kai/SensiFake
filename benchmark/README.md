# DeepfakeBench Effort evaluation

`deepfakebench_xception.py` evaluates
`annotations/human-train-v0/automatic_annotation/sensifake_complete_sensitivity.csv`
with DeepfakeBench's `effort` detector. It uses each row's verified
`source_label` as the authenticity target and reports metrics separately for
the complete CSV's `low`, `medium`, and `high` sensitivity levels. Reviewed
adjudicated levels take priority over model-only levels.

The evaluator imports the official DeepfakeBench Effort detector. Effort uses
CLIP ViT-L/14 at 224x224 with CLIP normalization. DeepfakeBench is kept outside
this repository.

First build the unified manifest:

```bash
uv run python scripts/datasets/build_unified_manifest.py
```

Install the benchmark extras and obtain DeepfakeBench:

```bash
uv sync --group benchmark
git clone https://github.com/SCLBD/DeepfakeBench.git external/DeepfakeBench
mkdir -p external/DeepfakeBench/preprocessing/dlib_tools
curl -L https://github.com/SCLBD/DeepfakeBench/releases/download/v1.0.0/shape_predictor_81_face_landmarks.dat \
  -o external/DeepfakeBench/preprocessing/dlib_tools/shape_predictor_81_face_landmarks.dat
```

Download the local CLIP model used by Effort:

```bash
uv run hf download openai/clip-vit-large-patch14 \
  --local-dir external/DeepfakeBench/huggingface/clip-vit-large-patch14
```

DeepfakeBench release `v1.0.1` does not include a pretrained Effort detector
checkpoint. Provide a compatible Effort checkpoint yourself, or train Effort
first, and put it in `external/DeepfakeBench/training/weights/`. Do not use
`xception_best.pth`; it is a different architecture.

Run from the repository root in Bash or WSL:

```bash
uv run python benchmark/deepfakebench_xception.py \
  --deepfakebench external/DeepfakeBench \
  --annotations annotations/human-train-v0/automatic_annotation/sensifake_complete_sensitivity.csv \
  --effort-model external/DeepfakeBench/huggingface/clip-vit-large-patch14 \
  --weights external/DeepfakeBench/training/weights/effort_clip_L14_trainOn_sdv14.pth
```

Outputs are written to `benchmark/results/deepfakebench-effort/`: the full
prediction CSV and JSON, plus one `low/`, `medium/`, and `high/` directory with
its prediction CSV, metrics JSON, confusion matrix, and probability plot.