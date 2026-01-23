"""SQLite database backend."""

import asyncio
import sqlite3
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from maven_core.protocols.database import Row


class SQLiteDatabase:
    """SQLite database backend.

    Suitable for development and small deployments.
    Uses aiosqlite-style async wrapper around sqlite3.
    """

    def __init__(
        self,
        path: str | None = None,
        **kwargs: Any,
    ) -> None:
        """Initialize SQLite database.

        Args:
            path: Path to SQLite database file. Defaults to ./data/maven.db
                  Use ":memory:" for in-memory database.
            **kwargs: Ignored (for compatibility with other backends)
        """
        if path == ":memory:":
            self.path = ":memory:"
        else:
            self.path = Path(path) if path else Path("./data/maven.db")
            if isinstance(self.path, Path):
                self.path.parent.mkdir(parents=True, exist_ok=True)

        self._conn: sqlite3.Connection | None = None
        self._lock = asyncio.Lock()
        self._in_transaction = False

    def _get_connection(self) -> sqlite3.Connection:
        """Get or create the database connection."""
        if self._conn is None:
            db_path = str(self.path) if isinstance(self.path, Path) else self.path
            self._conn = sqlite3.connect(db_path, check_same_thread=False)
            self._conn.row_factory = sqlite3.Row
        return self._conn

    def _convert_params(self, params: dict[str, Any] | None) -> tuple[str, tuple[Any, ...]]:
        """Convert named params to positional for sqlite3.

        SQLite3 supports :name syntax, but we use ? for simplicity.
        """
        if not params:
            return "", ()

        # Convert dict params to tuple, maintaining query param order
        return "", tuple(params.values())

    async def execute(
        self,
        query: str,
        params: dict[str, Any] | None = None,
    ) -> list[Row]:
        """Execute a query and return results."""
        async with self._lock:
            conn = self._get_connection()

            # Convert named parameters to positional
            # Replace :name with ? and build params tuple
            if params:
                import re
                param_names: list[str] = []

                def replace_param(match: Any) -> str:
                    name = match.group(1)
                    param_names.append(name)
                    return "?"

                query = re.sub(r":(\w+)", replace_param, query)
                param_values = tuple(params[name] for name in param_names)
            else:
                param_values = ()

            cursor = conn.execute(query, param_values)
            rows = cursor.fetchall()

            # Only auto-commit if not in a transaction
            if not self._in_transaction:
                conn.commit()

            return [Row(_data=dict(row)) for row in rows]

    async def execute_many(
        self,
        query: str,
        params_list: list[dict[str, Any]],
    ) -> None:
        """Execute a query multiple times with different parameters."""
        async with self._lock:
            conn = self._get_connection()

            # Convert named parameters
            if params_list:
                import re
                param_names: list[str] = []

                def replace_param(match: Any) -> str:
                    name = match.group(1)
                    if name not in param_names:
                        param_names.append(name)
                    return "?"

                query = re.sub(r":(\w+)", replace_param, query)
                params_tuples = [
                    tuple(p[name] for name in param_names) for p in params_list
                ]
            else:
                params_tuples = []

            conn.executemany(query, params_tuples)

            # Only auto-commit if not in a transaction
            if not self._in_transaction:
                conn.commit()

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator["SQLiteDatabase"]:
        """Start a transaction.

        Note: SQLite doesn't support nested transactions.
        """
        if self._in_transaction:
            # Already in a transaction, just yield self
            yield self
            return

        conn = self._get_connection()
        self._in_transaction = True
        try:
            yield self
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            self._in_transaction = False

    async def close(self) -> None:
        """Close the database connection."""
        if self._conn is not None:
            self._conn.close()
            self._conn = None
