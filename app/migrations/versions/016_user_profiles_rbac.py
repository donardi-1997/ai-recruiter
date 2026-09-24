"""add internal user profiles and RBAC

Revision ID: 016
Revises: 015
Create Date: 2026-09-24
"""

from alembic import op
import sqlalchemy as sa


revision = "016"
down_revision = "015"
branch_labels = None
depends_on = None


PERMISSIONS = [
    ("jobs.read", "Consultar vacantes."),
    ("jobs.manage", "Crear y administrar vacantes."),
    ("candidates.read", "Consultar candidatos y postulaciones."),
    ("candidates.evaluate", "Evaluar y rankear candidatos."),
    ("ranking.read", "Consultar rankings de candidatos."),
    ("integrations.manage", "Administrar integraciones del sistema."),
    ("employees.read", "Consultar empleados."),
    ("employees.create", "Crear empleados."),
    ("employees.update", "Editar empleados."),
    ("employees.disable", "Activar o desactivar empleados."),
    ("employees.roles.manage", "Administrar roles de empleados."),
    ("training.read", "Consultar el catalogo de capacitacion."),
    ("training.manage", "Crear y editar cursos, modulos y contenidos."),
    ("training.assign", "Asignar capacitacion a empleados."),
    ("training.results.read", "Consultar resultados de capacitacion."),
    ("training.consume", "Consumir cursos y lecciones asignadas."),
    ("training.quiz.take", "Presentar evaluaciones de capacitacion."),
    ("training.progress.read_own", "Consultar el progreso de capacitacion propio."),
    ("profile.read_own", "Consultar el perfil propio."),
    ("employee_scores.read", "Consultar calificaciones privadas de empleados."),
    ("employee_scores.create", "Agregar movimientos de puntuacion."),
    ("employee_scores.correct", "Corregir o anular movimientos de puntuacion."),
    ("employee_scores.export", "Exportar historial privado de puntuacion."),
]

ADMIN_PERMISSIONS = {
    "jobs.read",
    "jobs.manage",
    "candidates.read",
    "candidates.evaluate",
    "ranking.read",
    "integrations.manage",
    "employees.read",
    "employees.create",
    "employees.update",
    "employees.disable",
    "employees.roles.manage",
    "training.read",
    "training.manage",
    "training.assign",
    "training.results.read",
    "training.consume",
    "training.quiz.take",
    "training.progress.read_own",
    "profile.read_own",
}

EMPLOYEE_PERMISSIONS = {
    "training.read",
    "training.consume",
    "training.quiz.take",
    "training.progress.read_own",
    "profile.read_own",
}


def upgrade() -> None:
    op.create_table(
        "roles",
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("code"),
    )
    op.create_table(
        "permissions",
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("code"),
    )
    op.create_table(
        "user_profiles",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("cognito_sub", sa.Text(), nullable=False),
        sa.Column("email", sa.Text(), nullable=False),
        sa.Column("first_name", sa.Text(), nullable=True),
        sa.Column("last_name", sa.Text(), nullable=True),
        sa.Column("job_title", sa.Text(), nullable=True),
        sa.Column("department", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False, server_default="ACTIVE"),
        sa.Column("created_by_sub", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("cognito_sub", name="uq_user_profiles_cognito_sub"),
        sa.UniqueConstraint("email", name="uq_user_profiles_email"),
    )
    op.create_index(
        "idx_user_profiles_status",
        "user_profiles",
        ["status"],
        unique=False,
    )
    op.create_table(
        "user_roles",
        sa.Column("user_id", sa.Text(), nullable=False),
        sa.Column("role_code", sa.Text(), nullable=False),
        sa.Column("assigned_by_sub", sa.Text(), nullable=True),
        sa.Column(
            "assigned_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["user_profiles.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["role_code"],
            ["roles.code"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("user_id", "role_code"),
        sa.UniqueConstraint(
            "user_id",
            "role_code",
            name="uq_user_roles_user_role",
        ),
    )
    op.create_index(
        "idx_user_roles_role_code",
        "user_roles",
        ["role_code"],
        unique=False,
    )
    op.create_table(
        "role_permissions",
        sa.Column("role_code", sa.Text(), nullable=False),
        sa.Column("permission_code", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(
            ["permission_code"],
            ["permissions.code"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["role_code"],
            ["roles.code"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("role_code", "permission_code"),
        sa.UniqueConstraint(
            "role_code",
            "permission_code",
            name="uq_role_permissions_role_permission",
        ),
    )
    op.create_index(
        "idx_role_permissions_permission_code",
        "role_permissions",
        ["permission_code"],
        unique=False,
    )

    roles = sa.table(
        "roles",
        sa.column("code", sa.Text()),
        sa.column("name", sa.Text()),
        sa.column("description", sa.Text()),
    )
    permissions = sa.table(
        "permissions",
        sa.column("code", sa.Text()),
        sa.column("description", sa.Text()),
    )
    role_permissions = sa.table(
        "role_permissions",
        sa.column("role_code", sa.Text()),
        sa.column("permission_code", sa.Text()),
    )

    op.bulk_insert(
        roles,
        [
            {
                "code": "SUPER_ADMIN",
                "name": "Super administrador",
                "description": "Acceso total, incluidas las funciones privadas de Direccion.",
            },
            {
                "code": "ADMIN",
                "name": "Administrador",
                "description": "Administracion de reclutamiento, empleados y capacitacion.",
            },
            {
                "code": "EMPLOYEE",
                "name": "Empleado",
                "description": "Acceso personal a capacitacion, progreso y perfil.",
            },
        ],
    )
    op.bulk_insert(
        permissions,
        [
            {"code": code, "description": description}
            for code, description in PERMISSIONS
        ],
    )

    all_codes = {code for code, _ in PERMISSIONS}
    grants = []
    for permission_code in sorted(all_codes):
        grants.append(
            {
                "role_code": "SUPER_ADMIN",
                "permission_code": permission_code,
            }
        )
    for permission_code in sorted(ADMIN_PERMISSIONS):
        grants.append(
            {
                "role_code": "ADMIN",
                "permission_code": permission_code,
            }
        )
    for permission_code in sorted(EMPLOYEE_PERMISSIONS):
        grants.append(
            {
                "role_code": "EMPLOYEE",
                "permission_code": permission_code,
            }
        )
    op.bulk_insert(role_permissions, grants)


def downgrade() -> None:
    op.drop_index(
        "idx_role_permissions_permission_code",
        table_name="role_permissions",
    )
    op.drop_table("role_permissions")
    op.drop_index("idx_user_roles_role_code", table_name="user_roles")
    op.drop_table("user_roles")
    op.drop_index("idx_user_profiles_status", table_name="user_profiles")
    op.drop_table("user_profiles")
    op.drop_table("permissions")
    op.drop_table("roles")
