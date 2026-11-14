import sqlalchemy as sa
from alembic import op

revision = "0002_site_branding"
down_revision = "0001_auth"


def upgrade():
    table = op.create_table(
        "site_branding",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("title", sa.String(64), nullable=False),
        sa.Column("portrait", sa.LargeBinary()),
        sa.Column("background", sa.LargeBinary()),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.CheckConstraint("id = 1"),
    )
    op.bulk_insert(table, [{"id": 1, "title": "Minecraft Panel", "revision": 0}])


def downgrade():
    op.drop_table("site_branding")
