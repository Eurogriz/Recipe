"""FTS5 full-text search for recipes.

Provides high-performance full-text search across recipe fields using
SQLite FTS5 virtual table. Supports trigram tokenization for substring matching.
"""

from __future__ import annotations

import logging
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

logger = logging.getLogger(__name__)


FTS5_SCHEMA_SQL = """
CREATE VIRTUAL TABLE IF NOT EXISTS recipe_fts USING fts5(
    recipe_id UNINDEXED,
    category,
    subcategory,
    binder_type,
    product_class,
    intended_use,
    tags,
    source_citations,
    content='recipe',
    tokenize='unicode61 remove_diacritics 2'
);

-- Trigger to keep FTS index in sync with recipe table
CREATE TRIGGER IF NOT EXISTS recipe_fts_insert AFTER INSERT ON recipe BEGIN
    INSERT INTO recipe_fts (recipe_id, category, subcategory, binder_type, product_class, intended_use, tags, source_citations)
    VALUES (
        NEW.id,
        NEW.category,
        NEW.subcategory,
        NEW.binder_type,
        NEW.product_class,
        NEW.intended_use,
        COALESCE(json_extract(NEW.metadata_json, '$.tags'), ''),
        ''
    );
END;

CREATE TRIGGER IF NOT EXISTS recipe_fts_delete AFTER DELETE ON recipe BEGIN
    DELETE FROM recipe_fts WHERE recipe_id = OLD.id;
END;

CREATE TRIGGER IF NOT EXISTS recipe_fts_update AFTER UPDATE ON recipe BEGIN
    DELETE FROM recipe_fts WHERE recipe_id = OLD.id;
    INSERT INTO recipe_fts (recipe_id, category, subcategory, binder_type, product_class, intended_use, tags, source_citations)
    VALUES (
        NEW.id,
        NEW.category,
        NEW.subcategory,
        NEW.binder_type,
        NEW.product_class,
        NEW.intended_use,
        COALESCE(json_extract(NEW.metadata_json, '$.tags'), ''),
        ''
    );
END;
"""


class FtsSearchService:
    """Full-text search service backed by SQLite FTS5.

    Maintains a virtual FTS5 table synchronized with the main recipe table
    via triggers. Queries return recipe IDs ranked by relevance.
    """

    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def initialize(self) -> None:
        """Create FTS5 virtual table and triggers if they don't exist."""
        async with self._engine.begin() as conn:
            await conn.execute(text(FTS5_SCHEMA_SQL))
            # Rebuild the FTS index in case of schema changes
            await conn.execute(text("INSERT INTO recipe_fts(recipe_fts) VALUES('rebuild');"))
        logger.info("FTS5 search index initialized")

    async def search(
        self,
        query: str,
        limit: int = 50,
        session: AsyncSession | None = None,
    ) -> list[str]:
        """Full-text search, returns recipe IDs ranked by relevance.

        Args:
            query: Search query (FTS5 query syntax).
            limit: Maximum results.
            session: Optional session to use (else opens own).

        Returns:
            List of recipe IDs.
        """
        # FTS5 query syntax: prefix queries with '*', phrase with '"'
        fts_query = self._build_fts_query(query)
        sql = text(
            """
            SELECT recipe_id, rank
            FROM recipe_fts
            WHERE recipe_fts MATCH :query
            ORDER BY rank
            LIMIT :limit
            """
        )
        if session is not None:
            result = await session.execute(sql, {"query": fts_query, "limit": limit})
        else:
            async with self._engine.connect() as conn:
                result = await conn.execute(sql, {"query": fts_query, "limit": limit})
        rows = result.all()
        return [row[0] for row in rows]

    def _build_fts_query(self, query: str) -> str:
        """Build FTS5 MATCH expression from user query.

        Sanitizes input, escapes special characters, and adds prefix '*' for
        substring matching.
        """
        # Remove FTS5 reserved characters that could break the query
        sanitized = query.replace('"', ' ').replace("'", " ").replace(":", " ")

        # Split into words and add prefix matching
        words = sanitized.split()
        if not words:
            return '""'  # Empty query

        # Each word becomes a prefix search term
        # Wrap in quotes for safety
        return " ".join(f'"{word}"*' for word in words if word)

    async def get_stats(self, session: AsyncSession) -> dict[str, int]:
        """Get FTS index statistics."""
        sql = text("SELECT COUNT(*) FROM recipe_fts")
        result = await session.execute(sql)
        total = result.scalar() or 0
        return {"total_indexed": total}
