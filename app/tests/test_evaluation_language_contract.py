from types import SimpleNamespace

from app.domains.jobs.profile import build_evaluation_text
from app.infrastructure.bedrock.prompts import (
    CANDIDATE_EVALUATION_PROMPT,
    REQUIREMENT_EXTRACTION_PROMPT,
)


def _system_template(prompt):
    return prompt.messages[0].prompt.template


def test_requirement_extraction_requires_spanish_and_ignores_validation_questions():
    template = _system_template(REQUIREMENT_EXTRACTION_PROMPT)

    assert "Redacta en ESPAÑOL" in template
    assert "Conserva sin traducir nombres oficiales" in template
    assert '"Preguntas por validar"' in template
    assert "NO las conviertas en requisitos" in template


def test_candidate_evaluation_preserves_extracted_requirement_wording():
    template = _system_template(CANDIDATE_EVALUATION_PROMPT)

    assert "Conserva exactamente el texto de cada requisito proporcionado" in template


def test_generated_validation_questions_are_not_sent_to_candidate_scoring():
    job = SimpleNamespace(
        title="Líder de Contact Center Comercial",
        description=(
            "Dirigir y gestionar el centro de contacto comercial.\n\n"
            "Responsabilidades\n"
            "- Liderar el equipo de contacto comercial.\n\n"
            "Preguntas por validar (no son requisitos de evaluación)\n"
            "- Confirmar si se requiere experiencia internacional."
        ),
        evaluation_profile={
            "responsibilities": ["Liderar el equipo de contacto comercial."],
            "assumptions_to_validate": [
                "Confirmar si se requiere experiencia internacional."
            ],
        },
    )

    evaluation_text = build_evaluation_text(job)

    assert "Dirigir y gestionar el centro de contacto comercial." in evaluation_text
    assert "Liderar el equipo de contacto comercial." in evaluation_text
    assert "Confirmar si se requiere experiencia internacional." not in evaluation_text
