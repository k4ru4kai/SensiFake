"""Verify retained policy arithmetic without importing permission-deferred code."""
import importlib.util
import json
from fractions import Fraction
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "experiments/fusion_calibration"


def verifier():
    spec = importlib.util.spec_from_file_location("recorded", ROOT / "verify_recorded_results.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_real_boundary_tie_is_fake():
    assert not Fraction(1, 2) > Fraction(1, 2)
    assert verifier().counts([1, 0], [1, 0]) == (1, 1, 0, 0)


def test_historical_weights_remain_recorded():
    path = ROOT / "results/historical_fixed_grid/fusion_calibration_validation_summary.json"
    values = json.loads(path.read_text())["weights"]
    assert [values[k] for k in ["W_L", "W_M", "W_H"]] == [0.3, 0.5, 0.93]


def test_exact_weights_remain_distinct_from_rounded_values():
    assert Fraction(1, 3) != Fraction("0.33")
    assert Fraction(2, 3) != Fraction("0.66")


def test_recorded_selected_policy_arithmetic():
    assert len(verifier().verify()) == 3
