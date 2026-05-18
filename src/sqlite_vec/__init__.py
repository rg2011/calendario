"""sqlite-vec integration for automatic vector search with SQLAlchemy models.

This module provides automatic synchronization between the CustomShiftEmbedding
SQLAlchemy model and a sqlite-vec vec0 virtual table. When you insert, update,
or delete a CustomShiftEmbedding record, the vec0 index is updated automatically
via SQLAlchemy event listeners — no manual sync needed.

Usage:
    # In your app startup (already done in src/bootstrap/startup.py):
    from src.sqlite_vec import init_db
    init_db(db, app.logger)

    # To search for similar embeddings:
    from src.sqlite_vec import serialize_f32, search_similar
    results = search_similar(conn, "custom_shift_embeddings", query_vector, limit=5)
    # Returns [(rowid, distance), ...] — use rowid to look up in custom_shift_embeddings
"""

import logging
import sqlite3
import struct
from typing import List, Optional, Tuple

from sqlalchemy import event

import sqlite_vec as sqlite_vec_lib  # type: ignore[import-untyped]

logger = logging.getLogger(__name__)


def load_extension(db: sqlite3.Connection, log: logging.Logger) -> None:
    """Load the sqlite-vec extension into a SQLite connection.

    Args:
        db: A sqlite3.Connection instance (can be obtained from Flask-SQLAlchemy).
        log: Logger instance for status messages.
    """
    try:
        db.enable_load_extension(True)
        sqlite_vec_lib.load(db)  # type: ignore[attr-defined]
        db.enable_load_extension(False)
        log.info("sqlite-vec extension loaded successfully")

        # Verify the extension is working
        (version,) = db.execute("SELECT vec_version();").fetchone()
        log.info("sqlite-vec version: %s", version)
    except Exception as e:
        log.warning("Failed to load sqlite-vec extension: %s", str(e))


def serialize_f32(vector: List[float]) -> bytes:
    """Serialize a list of floats to compact binary format for sqlite-vec.

    Args:
        vector: A list of float values representing the embedding.

    Returns:
        Bytes in the compact binary format expected by sqlite-vec.
    """
    return struct.pack("%sf" % len(vector), *vector)


def deserialize_f32(data: bytes, dimension: int) -> List[float]:
    """Deserialize binary data back to a list of floats.

    Args:
        data: Binary data from the database.
        dimension: The number of floats in the vector.

    Returns:
        A list of float values.
    """
    return list(struct.unpack("%sf" % dimension, data))


def create_vector_table(
    db_conn: sqlite3.Connection,
    table_name: str = "embeddings",
    column_name: str = "embedding",
    dimension: int = 768,
) -> None:
    """Create a virtual table for vector search using vec0.

    Args:
        db_conn: A sqlite3.Connection instance.
        table_name: Name of the virtual table to create.
        column_name: Name of the embedding column.
        dimension: Dimensionality of the vectors.
    """
    db_conn.execute(
        f"""
        CREATE VIRTUAL TABLE IF NOT EXISTS {table_name}
        USING vec0({column_name} float[{dimension}])
        """
    )


def search_similar(
    db_conn: sqlite3.Connection,
    table_name: str,
    query_embedding: List[float],
    limit: int = 10,
) -> List[Tuple[int, float]]:
    """Search for similar vectors using cosine distance.

    Args:
        db_conn: A sqlite3.Connection instance.
        table_name: Name of the vector virtual table.
        query_embedding: The query embedding as a list of floats.
        limit: Maximum number of results to return.

    Returns:
        A list of (rowid, distance) tuples sorted by similarity.
    """
    cursor = db_conn.execute(
        f"""
        SELECT rowid, distance FROM {table_name}
        WHERE embedding MATCH ?
        ORDER BY distance
        LIMIT ?
        """,
        [serialize_f32(query_embedding), limit],
    )
    return cursor.fetchall()


def _get_raw_connection(db) -> sqlite3.Connection:
    """Get a raw sqlite3 connection from a Flask-SQLAlchemy db instance."""
    return db.engine.raw_connection()


def _ensure_vec_table(
    conn: sqlite3.Connection,
    log: logging.Logger,
    dimension: int = 768,
) -> None:
    """Ensure the vec0 virtual table exists and is initialized.

    Args:
        conn: A sqlite3.Connection instance.
        log: Logger instance for status messages.
        dimension: Dimensionality of the vectors.
    """
    # Check if the vector table already exists
    tables = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='custom_shift_embeddings_vec'"
    ).fetchall()

    if not tables:
        log.info("Creating vec0 virtual table for custom_shift_embeddings...")

        # Create the vec0 virtual table
        create_vector_table(conn, "custom_shift_embeddings_vec", "embedding", dimension)

        try:
            conn.execute(
                "SELECT vector_init('custom_shift_embeddings', 'embedding', "
                "'type=FLOAT32,dimension={},distance=COSINE')".format(dimension)
            )
            log.info("Vector table initialized with FLOAT32, dim=%d, dist=COSINE", dimension)
        except Exception as e:
            # vector_init may fail if called on a vec0 table (redundant but harmless)
            log.debug("vector_init skipped (vec0 handles this): %s", str(e))

        conn.commit()
    else:
        log.info("Vec0 virtual table already exists")


def _sync_to_vec(
    mapper, target, operation: str, db=None, log: Optional[logging.Logger] = None
) -> None:
    """Internal helper to sync a CustomShiftEmbedding record with the vec0 table.

    This is called by SQLAlchemy event listeners after insert/update/delete.

    Args:
        mapper: The SQLAlchemy mapper.
        target: The target instance (CustomShiftEmbedding).
        operation: One of 'insert', 'update', or 'delete'.
        db: The Flask-SQLAlchemy db instance (for getting raw connection).
        log: Logger instance for status messages.
    """
    if log is None:
        log = logger

    try:
        embedding_data = getattr(target, "embedding", None)
        rowid = target.id

        raw_conn = _get_raw_connection(db)
        if not raw_conn:
            return

        if operation == "delete":
            # On delete, always remove from vec0 regardless of embedding data
            raw_conn.execute(
                "DELETE FROM custom_shift_embeddings_vec WHERE rowid = ?",
                [rowid],
            )
            log.info("Deleted embedding for rowid=%d from vec0 table (delete event)", rowid)

        elif embedding_data and len(embedding_data) > 0:
            # Deserialize the binary embedding to a list of floats
            dimension = len(embedding_data) // 4  # FLOAT32 = 4 bytes per float
            vector = deserialize_f32(embedding_data, dimension)

            if operation == "insert":
                raw_conn.execute(
                    "INSERT INTO custom_shift_embeddings_vec(rowid, embedding) VALUES (?, ?)",
                    [rowid, serialize_f32(vector)],
                )
                log.info("Inserted embedding for rowid=%d into vec0 (dim=%d)", rowid, dimension)

            elif operation == "update":
                raw_conn.execute(
                    "DELETE FROM custom_shift_embeddings_vec WHERE rowid = ?",
                    [rowid],
                )
                raw_conn.execute(
                    "INSERT INTO custom_shift_embeddings_vec(rowid, embedding) VALUES (?, ?)",
                    [rowid, serialize_f32(vector)],
                )
                log.info("Updated embedding for rowid=%d in vec0 (dim=%d)", rowid, dimension)

        raw_conn.commit()

    except Exception as e:
        logger.warning(
            "Failed to sync CustomShiftEmbedding (rowid=%s) to vec0 table (%s): %s",
            getattr(target, "id", None),
            operation,
            str(e),
        )


def init_db(db, log: Optional[logging.Logger] = None) -> None:
    """Initialize sqlite-vec and register event listeners for automatic sync.

    This function sets up the vec0 virtual table and registers SQLAlchemy
    event listeners that automatically keep it in sync with
    custom_shift_embeddings inserts, updates, and deletes.

    After calling this, you never need to manually manage the vec0 index:
    - INSERT into custom_shift_embeddings → auto-inserts into vec0
    - UPDATE custom_shift_embeddings → auto-updates vec0
    - DELETE from custom_shift_embeddings → auto-deletes from vec0

    Args:
        db: The Flask-SQLAlchemy db instance.
        log: Optional logger instance for status messages.
    """
    if log is None:
        log = logger

    try:
        # Get the raw connection and load the extension
        raw_conn = _get_raw_connection(db)

        log.info("Initializing sqlite-vec extension...")
        load_extension(raw_conn, log)

        # Ensure vec0 virtual table exists
        _ensure_vec_table(raw_conn, log, 768)

        raw_conn.close()

        # Register event listeners for automatic sync
        # We use a lambda that captures db and log at registration time
        from src.models import CustomShiftEmbedding

        event.listen(
            CustomShiftEmbedding,
            "after_insert",
            lambda mapper, target, conn: _sync_to_vec(mapper, target, "insert", db, log),
        )
        event.listen(
            CustomShiftEmbedding,
            "after_update",
            lambda mapper, target, conn: _sync_to_vec(mapper, target, "update", db, log),
        )
        event.listen(
            CustomShiftEmbedding,
            "after_delete",
            lambda mapper, target, conn: _sync_to_vec(mapper, target, "delete", db, log),
        )

        log.info("sqlite-vec event listeners registered for CustomShiftEmbedding")

    except Exception as e:
        log.error("Error initializing sqlite-vec: %s", str(e))
