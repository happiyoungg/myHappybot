"""Versioned, deterministic asset-allocation policy."""

from __future__ import annotations

from collections.abc import Mapping

from .schemas import RiskProfile

POLICY_VERSION = "allocation_policy_v1"

ALLOCATION_PERCENTAGES: Mapping[RiskProfile, tuple[tuple[str, int], ...]] = {
    RiskProfile.CONSERVATIVE: (
        ("cash", 10),
        ("savings", 15),
        ("bond", 40),
        ("equity_index", 20),
        ("retirement", 15),
    ),
    RiskProfile.BALANCED: (
        ("cash", 5),
        ("savings", 10),
        ("bond", 25),
        ("equity_index", 40),
        ("retirement", 20),
    ),
    RiskProfile.GROWTH: (
        ("cash", 5),
        ("savings", 5),
        ("bond", 10),
        ("equity_index", 55),
        ("retirement", 25),
    ),
}


def validate_policy() -> None:
    """Fail early when a policy edit no longer allocates 100 percent."""
    for risk_profile, allocation in ALLOCATION_PERCENTAGES.items():
        total = sum(percentage for _, percentage in allocation)
        if total != 100:
            raise RuntimeError(f"{risk_profile.value} allocation must total 100, got {total}.")


validate_policy()
