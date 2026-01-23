"""Database protocol for SQL backends."""

from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class Row:
    """Type-safe row access with attribute-style access."""

    _data: dict[str, Any] = field(repr=False)

    def __getattr__(self, name: str) -> Any:
        if name.startswith("_"):
            return object.__getattribute__(self, name)
        try:
            return self._data[name]
        except KeyError:
            raise AttributeError(f"Row has no column '{name}'") from None

    def __getitem__(self, key: str) -> Any:
        return self._data[key]

    def __contains__(self, key: str) -> bool:
        return key in self._data

    def keys(self) -> list[str]:
        """Return column names."""
        return list(self._data.keys())

    def values(self) -> list[Any]:
        """Return column values."""
        return list(self._data.values())

    def to_dict(self) -> dict[str, Any]:
        """Convert row to dictionary."""
        return dict(self._data)


class Database(Protocol):
    """Protocol for SQL database backends (D1, PostgreSQL, SQLite)."""

    async def execute(
        self,
        query: str,
        params: dict[str, Any] | None = None,
    ) -> list[Row]:
        """Execute a query and return results."""
        ...

    async def execute_many(
        self,
        query: str,
        params_list: list[dict[str, Any]],
    ) -> None:
        """Execute a query multiple times with different parameters."""
        ...

    def transaction(self) -> AbstractAsyncContextManager["Database"]:
        """Start a transaction. Commits on exit, rolls back on exception."""
        ...
