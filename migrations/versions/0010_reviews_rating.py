"""reviews: optional comment, moderation state, one review per user and establishment

Revision ID: 0010_reviews_rating
Revises: 0009_establishment_geo

- `reviews.comment` pasa a ser opcional (reseña solo con estrellas).
- Moderación: `status` (VISIBLE/HIDDEN), `comment_status` (VISIBLE/BLOCKED), `moderation_category`,
  `moderation_reason`, `flagged_for_review` y `edited_at` en `reviews`; `comment_status`,
  `moderation_category`, `moderation_reason`, `flagged_for_review` y `updated_at` en `review_replies`.
- `display_order` en `review_images`.
- **Duplicados:** antes de crear `uq_reviews_user_establishment` se BORRAN las reseñas repetidas de un
  mismo usuario en un mismo establecimiento y se conserva la más reciente (mayor id). El seed demo no
  genera duplicados; esto protege datos creados a mano. `downgrade()` no puede restaurar esas filas.
- `ck_reviews_rating_range` (1 a 5) e índice `(establishment_id, status, created_at)`.
- Los agregados (`rating_*`, `ranking_score`) se crearon en 0009; aquí se recalculan contando solo las
  reseñas VISIBLE (todas lo son al aplicar la migración) por si se borraron duplicados.
"""

from alembic import op
import sqlalchemy as sa

from app.core.config import settings

revision = "0010_reviews_rating"
down_revision = "0009_establishment_geo"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("reviews", "comment", existing_type=sa.Text(), nullable=True)
    # Un texto vacío equivale a no haber escrito comentario (así lo deja también downgrade()).
    op.execute("UPDATE reviews SET comment = NULL WHERE btrim(comment) = ''")
    op.add_column("reviews", sa.Column("status", sa.String(length=20), nullable=False, server_default="VISIBLE"))
    op.add_column(
        "reviews", sa.Column("comment_status", sa.String(length=20), nullable=False, server_default="VISIBLE")
    )
    op.add_column("reviews", sa.Column("moderation_category", sa.String(length=40), nullable=True))
    op.add_column("reviews", sa.Column("moderation_reason", sa.Text(), nullable=True))
    op.add_column(
        "reviews", sa.Column("flagged_for_review", sa.Boolean(), nullable=False, server_default=sa.false())
    )
    op.add_column("reviews", sa.Column("edited_at", sa.DateTime(timezone=True), nullable=True))

    # Reseñas repetidas: se conserva la más reciente de cada (user_id, establishment_id).
    op.execute(
        """
        DELETE FROM reviews r USING reviews r2
        WHERE r.user_id = r2.user_id AND r.establishment_id = r2.establishment_id AND r.id < r2.id
        """
    )
    # Cualquier valor fuera de rango (no debería haberlo: la API siempre exigió 1..5) se acota.
    op.execute("UPDATE reviews SET rating = LEAST(GREATEST(rating, 1), 5) WHERE rating NOT BETWEEN 1 AND 5")
    op.create_unique_constraint("uq_reviews_user_establishment", "reviews", ["user_id", "establishment_id"])
    op.create_check_constraint("ck_reviews_rating_range", "reviews", "rating BETWEEN 1 AND 5")
    op.create_index(
        "ix_reviews_establishment_status_created", "reviews", ["establishment_id", "status", "created_at"]
    )

    op.add_column(
        "review_images", sa.Column("display_order", sa.Integer(), nullable=False, server_default="0")
    )

    op.add_column(
        "review_replies",
        sa.Column("comment_status", sa.String(length=20), nullable=False, server_default="VISIBLE"),
    )
    op.add_column("review_replies", sa.Column("moderation_category", sa.String(length=40), nullable=True))
    op.add_column("review_replies", sa.Column("moderation_reason", sa.Text(), nullable=True))
    op.add_column(
        "review_replies",
        sa.Column("flagged_for_review", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "review_replies",
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.execute("UPDATE review_replies SET updated_at = created_at")

    # Recalcular agregados (solo VISIBLE), por si se borraron duplicados.
    op.execute(
        """
        UPDATE establishments AS e
        SET rating_count = COALESCE(s.c, 0),
            rating_sum = COALESCE(s.s, 0),
            rating_avg = CASE WHEN s.c > 0 THEN ROUND((s.s::numeric / s.c), 2)::float END
        FROM establishments AS e2
        LEFT JOIN (
            SELECT establishment_id, COUNT(*) AS c, SUM(rating) AS s
            FROM reviews WHERE status = 'VISIBLE' GROUP BY establishment_id
        ) AS s ON s.establishment_id = e2.id
        WHERE e2.id = e.id
        """
    )
    op.execute(
        sa.text(
            "UPDATE establishments SET ranking_score = ROUND(((rating_sum + :m * :c) / (rating_count + :m))::numeric, 4)::float"
        ).bindparams(m=float(settings.ranking_min_reviews), c=float(settings.ranking_prior_mean))
    )


def downgrade() -> None:
    # Las reseñas duplicadas borradas en upgrade() no se pueden restaurar.
    op.drop_column("review_replies", "updated_at")
    op.drop_column("review_replies", "flagged_for_review")
    op.drop_column("review_replies", "moderation_reason")
    op.drop_column("review_replies", "moderation_category")
    op.drop_column("review_replies", "comment_status")
    op.drop_column("review_images", "display_order")
    op.drop_index("ix_reviews_establishment_status_created", table_name="reviews")
    op.drop_constraint("ck_reviews_rating_range", "reviews", type_="check")
    op.drop_constraint("uq_reviews_user_establishment", "reviews", type_="unique")
    op.drop_column("reviews", "edited_at")
    op.drop_column("reviews", "flagged_for_review")
    op.drop_column("reviews", "moderation_reason")
    op.drop_column("reviews", "moderation_category")
    op.drop_column("reviews", "comment_status")
    op.drop_column("reviews", "status")
    # Las reseñas sin texto reciben un texto vacío para volver a NOT NULL.
    op.execute("UPDATE reviews SET comment = '' WHERE comment IS NULL")
    op.alter_column("reviews", "comment", existing_type=sa.Text(), nullable=False)
