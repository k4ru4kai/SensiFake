"""Check three saved selected policies only; no sweeps, folds, models or images."""
import csv
import json
from fractions import Fraction
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def counts(truth, predicted):
    tp = sum(y == 1 and p == 1 for y, p in zip(truth, predicted, strict=True))
    tn = sum(y == 0 and p == 0 for y, p in zip(truth, predicted, strict=True))
    fp = sum(y == 0 and p == 1 for y, p in zip(truth, predicted, strict=True))
    fn = sum(y == 1 and p == 0 for y, p in zip(truth, predicted, strict=True))
    return tp, tn, fp, fn


def verify():
    rows = list(csv.DictReader((ROOT / "inputs/validation_seed20.csv").open()))
    assert len(rows) == 450 and all(r["split"] == "validation" for r in rows)
    assert len({r["training_run_id"] for r in rows}) == 1
    truth = [int(r["true_real_fake"]) for r in rows]
    settings = [
        ("historical_fixed_grid", [0.3, 0.5, 0.93], 0.05,
         "fusion_calibration_validation_summary.json", "selected_fusion"),
        ("joint_weight_grid", [0.45, 0.5, 1.0], 0.065,
         "fusion_weight_calibration_summary.json", "selected_fusion_metrics"),
        ("exact_breakpoints", [Fraction(1, 3), Fraction(2, 3), Fraction(1)],
         Fraction(12475616, 348775107), "final_epsilon_summary.json", "selected_fusion_metrics"),
    ]
    result = []
    for name, weights, epsilon, filename, key in settings:
        predicted = []
        for r in rows:
            if name == "exact_breakpoints":
                rho = sum(w * Fraction.from_float(float(r[c])) for w, c in
                          zip(weights, ["p_low", "p_medium", "p_high"], strict=True))
                fake = Fraction.from_float(float(r["p_fake"])) >= Fraction(1, 2) - epsilon * rho
            else:
                rho = sum(w * float(r[c]) for w, c in
                          zip(weights, ["p_low", "p_medium", "p_high"], strict=True))
                fake = float(r["p_real"]) <= 0.5 + epsilon * rho
            predicted.append(int(fake))
        tp, tn, fp, fn = counts(truth, predicted)
        metrics = {"accuracy": (tp + tn) / 450, "fake_recall": tp / (tp + fn),
                   "fake_precision": tp / (tp + fp), "fake_fnr": fn / (tp + fn)}
        recorded = json.loads((ROOT / "results" / name / filename).read_text())[key]
        assert all(abs(recorded[k] - v) < 1e-12 for k, v in metrics.items())
        result.append({"experiment": name, "status": "VERIFIED saved arithmetic", **metrics})
    return result


if __name__ == "__main__":
    print(json.dumps(verify(), indent=2))
