"""initial schema

Revision ID: 0001_initial
Revises:
Create Date: 2026-05-09 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Rozszerzenie pgcrypto dla gen_random_uuid()
    op.execute('CREATE EXTENSION IF NOT EXISTS "pgcrypto";')

    user_role = postgresql.ENUM(
        "USER", "ADMIN", name="userrole", create_type=True
    )
    user_role.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "users",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("username", sa.String(64), nullable=False, unique=True),
        sa.Column("hashed_password", sa.Text(), nullable=False),
        sa.Column(
            "role",
            postgresql.ENUM(
                "USER", "ADMIN", name="userrole", create_type=False
            ),
            nullable=False,
            server_default="USER",
        ),
        sa.Column("department", sa.String(128), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_users_username", "users", ["username"], unique=True)

    op.create_table(
        "company_policies",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column(
            "uploaded_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    op.create_table(
        "security_incidents",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("original_prompt", sa.Text(), nullable=False),
        sa.Column("sanitized_prompt", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_security_incidents_user_id", "security_incidents", ["user_id"]
    )
    op.create_index(
        "ix_security_incidents_created_at",
        "security_incidents",
        ["created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_security_incidents_created_at", table_name="security_incidents"
    )
    op.drop_index(
        "ix_security_incidents_user_id", table_name="security_incidents"
    )
    op.drop_table("security_incidents")
    op.drop_table("company_policies")
    op.drop_index("ix_users_username", table_name="users")
    op.drop_table("users")
    op.execute("DROP TYPE IF EXISTS userrole;")
