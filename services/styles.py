from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class StyleProfile:
    style_id: str
    prompt_rules: list[str]
    harmony_rules: list[str]
    evaluation_rules: list[str]
    pitch_pattern: list[int]


ANCIENT_CN_PROFILE = StyleProfile(
    style_id="ancient_cn",
    prompt_rules=["pentatonic", "stepwise_motion", "phrase_balance"],
    harmony_rules=["I-IV-V preference"],
    evaluation_rules=["style_consistency_score >= 0.8"],
    pitch_pattern=[0, 2, 5, 7, 9, 7, 5, 2],
)

CUSTOM_PROFILE = StyleProfile(
    style_id="custom",
    prompt_rules=["free_style"],
    harmony_rules=["diatonic_preference"],
    evaluation_rules=["melodic_coherence_score >= 0.7"],
    pitch_pattern=[0, 2, 4, 5, 7, 9, 11, 12],
)


def get_style_profile(style: str) -> StyleProfile:
    if style == "ancient_cn":
        return ANCIENT_CN_PROFILE
    return CUSTOM_PROFILE
