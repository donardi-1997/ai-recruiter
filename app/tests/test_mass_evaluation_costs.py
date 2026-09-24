"""Mass evaluation cost calculator contracts."""

from types import SimpleNamespace

from app.domains.ranking import costs


def _settings():
    return SimpleNamespace(
        nova_input_usd_per_million=0.30,
        nova_output_usd_per_million=2.50,
        input_tokens_per_deep_candidate=4500,
        output_tokens_per_deep_candidate=600,
        fast_default_deep_candidates=1000,
        cost_margin_percent=25.0,
        max_deep_requests_per_minute=2000,
    )


def test_exhaustive_cost_scales_with_candidate_count(monkeypatch):
    monkeypatch.setattr(costs, "get_mass_evaluation_cost_settings", _settings)

    result = costs.estimate_mass_evaluation_cost(
        candidate_count=27_000,
        mode="exhaustive",
    )

    assert result["candidate_count"] == 27_000
    assert result["deep_candidate_count"] == 27_000
    assert result["shallow_candidate_count"] == 0
    assert result["input_tokens_estimated"] == 121_500_000
    assert result["output_tokens_estimated"] == 16_200_000
    assert result["estimated_cost_usd"] == 76.95
    assert result["estimated_cost_with_margin_usd"] == 96.1875
    assert result["theoretical_min_seconds"] == 810


def test_fast_cost_limits_deep_ai_to_top_n(monkeypatch):
    monkeypatch.setattr(costs, "get_mass_evaluation_cost_settings", _settings)

    result = costs.estimate_mass_evaluation_cost(
        candidate_count=27_000,
        mode="fast",
        deep_candidate_count=1_000,
    )

    assert result["candidate_count"] == 27_000
    assert result["deep_candidate_count"] == 1_000
    assert result["shallow_candidate_count"] == 26_000
    assert result["estimated_cost_usd"] == 2.85
    assert result["estimated_cost_with_margin_usd"] == 3.5625
    assert result["theoretical_min_seconds"] == 30
    assert result["target_seconds"] == 120


def test_cost_estimate_uses_candidate_count_as_primary_variable(monkeypatch):
    monkeypatch.setattr(costs, "get_mass_evaluation_cost_settings", _settings)

    small = costs.estimate_mass_evaluation_cost(
        candidate_count=1_000,
        mode="exhaustive",
    )
    large = costs.estimate_mass_evaluation_cost(
        candidate_count=10_000,
        mode="exhaustive",
    )

    assert large["estimated_cost_usd"] == small["estimated_cost_usd"] * 10
