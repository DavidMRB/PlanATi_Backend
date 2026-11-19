"""establishment location, type and rating aggregates

Revision ID: 0009_establishment_geo
Revises: 0008_notifications

Ubicación: `location_source`, `google_place_id`, `city`, `establishment_type` e índice
`(latitude, longitude)` para el prefiltro por bounding box de `/nearby` y `/map`.

Agregados de puntuación (`rating_count`, `rating_sum`, `rating_avg`, `ranking_score`): el plan los
ubicaba en 0010, pero el directorio y el mapa de B2 ya ordenan y filtran por ellos y dejan de
devolver las reseñas, así que se adelantan aquí. El backfill usa
ranking_score = (rating_sum + m·C) / (rating_count + m) con RANKING_MIN_REVIEWS (m) y
RANKING_PRIOR_MEAN (C) de la configuración. `scripts/recompute_ratings.py` recalcula todo desde cero.
"""

from alembic import op
import sqlalchemy as sa

from app.core.config import settings

revision = "0009_establishment_geo"
down_revision = "0008_notifications"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("establishments", sa.Column("location_source", sa.String(length=20), nullable=True))
    op.add_column("establishments", sa.Column("google_place_id", sa.String(length=255), nullable=True))
    op.add_column("establishments", sa.Column("city", sa.String(length=80), nullable=True))
    op.add_column(
        "establishments",
        sa.Column("establishment_type", sa.String(length=30), nullable=False, server_default="RESTAURANT"),
    )
    op.create_index("ix_establishments_city", "establishments", ["city"], unique=False)
    op.create_index("ix_establishments_establishment_type", "establishments", ["establishment_type"], unique=False)
    op.create_index("ix_establishments_lat_lng", "establishments", ["latitude", "longitude"], unique=False)

    op.add_column("establishments", sa.Column("rating_count", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("establishments", sa.Column("rating_sum", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("establishments", sa.Column("rating_avg", sa.Float(), nullable=True))
    op.add_column("establishments", sa.Column("ranking_score", sa.Float(), nullable=True))
    op.create_index("ix_establishments_ranking_score", "establishments", ["ranking_score"], unique=False)

    # Backfill (SQL de PostgreSQL: las migraciones solo corren contra PostgreSQL).
    op.execute(
        """
        UPDATE establishments AS e
        SET rating_count = s.c, rating_sum = s.s, rating_avg = ROUND((s.s::numeric / s.c), 2)::float
        FROM (SELECT establishment_id, COUNT(*) AS c, SUM(rating) AS s FROM reviews GROUP BY establishment_id) AS s
        WHERE s.establishment_id = e.id
        """
    )
    op.execute(
        sa.text(
            "UPDATE establishments SET ranking_score = ROUND(((rating_sum + :m * :c) / (rating_count + :m))::numeric, 4)::float"
        ).bindparams(m=float(settings.ranking_min_reviews), c=float(settings.ranking_prior_mean))
    )


def downgrade() -> None:
    op.drop_index("ix_establishments_ranking_score", table_name="establishments")
    op.drop_column("establishments", "ranking_score")
    op.drop_column("establishments", "rating_avg")
    op.drop_column("establishments", "rating_sum")
    op.drop_column("establishments", "rating_count")
    op.drop_index("ix_establishments_lat_lng", table_name="establishments")
    op.drop_index("ix_establishments_establishment_type", table_name="establishments")
    op.drop_index("ix_establishments_city", table_name="establishments")
    op.drop_column("establishments", "establishment_type")
    op.drop_column("establishments", "city")
    op.drop_column("establishments", "google_place_id")
    op.drop_column("establishments", "location_source")
