"""Tenant-scoped company context for vacancy enrichment."""

from __future__ import annotations

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.domains.jobs.company_context_model import CompanyContext


class CompanyContextPayload(BaseModel):
    business_summary: str
    operating_context: list[str] = Field(default_factory=list)
    business_capabilities: list[str] = Field(default_factory=list)
    culture_principles: list[str] = Field(default_factory=list)
    talent_principles: list[str] = Field(default_factory=list)
    recruiter_guidance: list[str] = Field(default_factory=list)

    model_config = {"extra": "forbid"}


ASIATI_CONTEXT_V1 = CompanyContextPayload(
    business_summary=(
        "ASIATI Corp is an international-expansion ecosystem that combines "
        "strategy, origin control and operational execution across Asia and Latin America."
    ),
    operating_context=[
        "International expansion and market-entry work across multiple countries.",
        "Cross-border collaboration between teams, suppliers and customers.",
        "Operational execution involving logistics, documentation, customs and commercial follow-up.",
        "Decision making that balances growth, margin, cost, risk and execution quality.",
    ],
    business_capabilities=[
        "International expansion strategy and market development.",
        "Supplier, product and origin validation and control.",
        "Logistics and operational coordination.",
        "Commercial scaling and structured follow-up.",
        "Data-informed optimization and measurable business execution.",
    ],
    culture_principles=[
        "Business-minded decision making.",
        "Structured execution rather than improvisation.",
        "Structured adaptability as markets and operations change.",
        "Data, measurable results and continuous optimization.",
        "Method, control and long-term thinking.",
    ],
    talent_principles=[
        "Professional growth and continuous learning.",
        "Collaboration across locations, cultures and perspectives.",
        "Continuous improvement and innovation.",
        "Curiosity, initiative and practical problem solving.",
    ],
    recruiter_guidance=[
        "Use this context to improve role responsibilities, competencies, domain knowledge and reasonable KPIs.",
        "Do not convert company culture into automatic hard filters for applicants.",
        "Do not claim ASIATI uses a specific tool, technology or certification unless the job draft explicitly supports it.",
        "Put uncertain role-specific implications in assumptions_to_validate for HR review.",
    ],
).model_dump()


def get_active_company_context(
    db: Session,
    *,
    owner_sub: str,
) -> CompanyContext | None:
    """Return the newest active company context visible to one tenant."""
    return (
        db.query(CompanyContext)
        .filter(
            CompanyContext.owner_sub == owner_sub,
            CompanyContext.status == "ACTIVE",
        )
        .order_by(CompanyContext.version.desc())
        .first()
    )


def validated_context_payload(row: CompanyContext) -> CompanyContextPayload:
    """Validate persisted JSON before it can enter a model prompt."""
    return CompanyContextPayload.model_validate(row.context)


def ensure_asiati_context_v1(
    db: Session,
    *,
    owner_sub: str,
) -> CompanyContext:
    """Idempotently provision ASIATI context v1 for an authenticated tenant.

    If a newer active context already exists, preserve it. This helper exists so
    the application never needs a hardcoded account identifier in migrations.
    """
    active = get_active_company_context(db, owner_sub=owner_sub)
    if active is not None:
        validated_context_payload(active)
        return active

    existing_v1 = (
        db.query(CompanyContext)
        .filter(
            CompanyContext.owner_sub == owner_sub,
            CompanyContext.version == 1,
        )
        .first()
    )
    if existing_v1 is not None:
        existing_v1.status = "ACTIVE"
        existing_v1.organization_name = "ASIATI Corp"
        existing_v1.context = dict(ASIATI_CONTEXT_V1)
        db.commit()
        db.refresh(existing_v1)
        return existing_v1

    context = CompanyContext(
        owner_sub=owner_sub,
        organization_name="ASIATI Corp",
        version=1,
        status="ACTIVE",
        context=dict(ASIATI_CONTEXT_V1),
    )
    db.add(context)
    db.commit()
    db.refresh(context)
    return context
