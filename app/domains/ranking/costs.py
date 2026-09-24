"""Cost planning helpers for mass candidate evaluation."""

from __future__ import annotations

import math

from app.config import get_mass_evaluation_cost_settings


def estimate_mass_evaluation_cost(
    *,
    candidate_count: int,
    mode: str,
    deep_candidate_count: int | None = None,
) -> dict:
    if candidate_count < 0:
        raise ValueError("candidate_count must be non-negative")

    normalized_mode = str(mode or "").strip().lower()
    if normalized_mode not in {"fast", "exhaustive"}:
        raise ValueError("unsupported mass evaluation mode")

    settings = get_mass_evaluation_cost_settings()

    if normalized_mode == "exhaustive":
        deep_count = candidate_count
    else:
        requested = (
            settings.fast_default_deep_candidates
            if deep_candidate_count is None
            else max(1, int(deep_candidate_count))
        )
        deep_count = min(candidate_count, requested)

    shallow_count = max(candidate_count - deep_count, 0)

    input_tokens = deep_count * settings.input_tokens_per_deep_candidate
    output_tokens = deep_count * settings.output_tokens_per_deep_candidate

    input_cost = (
        input_tokens / 1_000_000
    ) * settings.nova_input_usd_per_million
    output_cost = (
        output_tokens / 1_000_000
    ) * settings.nova_output_usd_per_million

    estimated_cost = input_cost + output_cost
    cost_with_margin = estimated_cost * (
        1.0 + settings.cost_margin_percent / 100.0
    )

    theoretical_min_seconds = (
        math.ceil(
            deep_count
            / settings.max_deep_requests_per_minute
            * 60
        )
        if deep_count
        else 0
    )

    return {
        "mode": normalized_mode,
        "candidate_count": candidate_count,
        "deep_candidate_count": deep_count,
        "shallow_candidate_count": shallow_count,
        "input_tokens_estimated": input_tokens,
        "output_tokens_estimated": output_tokens,
        "estimated_cost_usd": round(estimated_cost, 4),
        "estimated_cost_with_margin_usd": round(cost_with_margin, 4),
        "margin_percent": settings.cost_margin_percent,
        "nova_input_usd_per_million": settings.nova_input_usd_per_million,
        "nova_output_usd_per_million": settings.nova_output_usd_per_million,
        "input_tokens_per_deep_candidate": (
            settings.input_tokens_per_deep_candidate
        ),
        "output_tokens_per_deep_candidate": (
            settings.output_tokens_per_deep_candidate
        ),
        "max_deep_requests_per_minute": (
            settings.max_deep_requests_per_minute
        ),
        "theoretical_min_seconds": theoretical_min_seconds,
        "target_seconds": 120 if normalized_mode == "fast" else None,
        "includes": [
            "Inferencia Nova estimada para los candidatos con análisis profundo.",
        ],
        "excludes": [
            "Costos fijos de infraestructura ya encendida.",
            "Variaciones de búsqueda vectorial, reintentos y transferencia.",
            "Cambios futuros en tarifas de AWS.",
        ],
        "disclaimer": (
            "Esta es una estimación de planeación. El costo real puede variar "
            "por longitud de CVs, tokens, reintentos, cuotas y tarifas vigentes "
            "de AWS."
        ),
    }
