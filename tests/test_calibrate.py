from tend.calibrate import from_ratios


def test_needs_five_samples():
    assert from_ratios([2, 2, 2, 2]).factor == 1.0
    assert from_ratios([1.2, 1.5, 1.4, 3.0, 1.1]).factor == 1.4


def test_median_resists_outliers_and_is_clamped():
    assert from_ratios([1, 1, 1, 1, 50]).factor == 1
    assert from_ratios([9] * 6).factor == 3.0
    assert from_ratios([0.1] * 6).factor == 0.5
