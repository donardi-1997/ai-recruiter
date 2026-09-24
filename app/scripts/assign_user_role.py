"""One-time CLI for assigning an internal RBAC role to an existing Cognito user."""

import argparse

from app.access_control import ADMIN, EMPLOYEE, SUPER_ADMIN
from app.db import SessionLocal
from app.domains.employees import service


ROLE_CHOICES = (SUPER_ADMIN, ADMIN, EMPLOYEE)


def parse_args():
    parser = argparse.ArgumentParser(
        description="Assign an AI Recruiter internal role to an existing Cognito user."
    )
    parser.add_argument("--email", required=True)
    parser.add_argument("--role", required=True, choices=ROLE_CHOICES)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    db = SessionLocal()
    try:
        profile = service.ensure_existing_cognito_profile(
            db,
            email=args.email,
            created_by_sub="bootstrap-script",
        )
        service.set_employee_role(
            db,
            profile.id,
            role_code=args.role,
            assigned_by_sub="bootstrap-script",
        )
        print(
            f"Assigned {args.role} to {profile.email} "
            f"(profile_id={profile.id})."
        )
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
