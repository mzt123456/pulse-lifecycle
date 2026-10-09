"""评测口径用例：判定规则本身错了，指标再漂亮也没意义。"""

from eval.diagnosis_eval import cause_matches, normalize, percentile


def test_normalize_strips_punctuation_and_whitespace() -> None:
    assert normalize("密封圈老化，导致渗漏。") == "密封圈老化导致渗漏"
    assert normalize("  O 形圈  破损 ") == "O形圈破损"
    assert normalize(None) == ""


def test_cause_match_accepts_longer_or_shorter_wording() -> None:
    assert cause_matches("密封圈老化导致密封失效", "密封圈老化")
    assert cause_matches("阀芯磨粒磨损", "泥浆含砂量大导致阀芯磨粒磨损")
    assert cause_matches("密封面拉伤。", "密封面拉伤")


def test_cause_match_rejects_different_causes() -> None:
    assert not cause_matches("电池组电量耗尽", "密封圈老化")
    assert not cause_matches("", "密封圈老化")
    assert not cause_matches(None, None)


def test_percentile_is_robust_to_small_samples() -> None:
    assert percentile([], 0.95) == 0.0
    assert percentile([10.0], 0.95) == 10.0
    # 20 个样本时 P95 落在第 19 个（下标 18），与最近秩口径一致
    values = [float(i) for i in range(20)]
    assert percentile(values, 0.95) == 18.0
