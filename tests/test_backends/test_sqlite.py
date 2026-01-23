"""Tests for SQLite database backend."""

import pytest

from maven_core.backends.database.sqlite import SQLiteDatabase


@pytest.fixture
async def db():
    """Create an in-memory SQLite database."""
    database = SQLiteDatabase(path=":memory:")
    # Create a test table
    await database.execute("""
        CREATE TABLE users (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            email TEXT UNIQUE
        )
    """)
    yield database
    await database.close()


class TestSQLiteDatabase:
    """Tests for SQLiteDatabase."""

    @pytest.mark.asyncio
    async def test_execute_insert_and_select(self, db):
        """Test inserting and selecting data."""
        await db.execute(
            "INSERT INTO users (id, name, email) VALUES (:id, :name, :email)",
            {"id": "1", "name": "Alice", "email": "alice@example.com"},
        )

        rows = await db.execute("SELECT * FROM users WHERE id = :id", {"id": "1"})
        assert len(rows) == 1
        assert rows[0].name == "Alice"
        assert rows[0].email == "alice@example.com"

    @pytest.mark.asyncio
    async def test_row_attribute_access(self, db):
        """Test Row attribute-style access."""
        await db.execute(
            "INSERT INTO users (id, name, email) VALUES (:id, :name, :email)",
            {"id": "1", "name": "Bob", "email": "bob@example.com"},
        )

        rows = await db.execute("SELECT * FROM users")
        row = rows[0]

        # Attribute access
        assert row.id == "1"
        assert row.name == "Bob"

        # Dictionary access
        assert row["email"] == "bob@example.com"

        # Contains check
        assert "name" in row

        # Keys and values
        assert "id" in row.keys()
        assert "Bob" in row.values()

    @pytest.mark.asyncio
    async def test_row_missing_attribute(self, db):
        """Test accessing a missing attribute raises AttributeError."""
        await db.execute(
            "INSERT INTO users (id, name, email) VALUES (:id, :name, :email)",
            {"id": "1", "name": "Charlie", "email": "charlie@example.com"},
        )

        rows = await db.execute("SELECT * FROM users")
        row = rows[0]

        with pytest.raises(AttributeError, match="nonexistent"):
            _ = row.nonexistent

    @pytest.mark.asyncio
    async def test_execute_many(self, db):
        """Test inserting multiple rows."""
        await db.execute_many(
            "INSERT INTO users (id, name, email) VALUES (:id, :name, :email)",
            [
                {"id": "1", "name": "Alice", "email": "alice@example.com"},
                {"id": "2", "name": "Bob", "email": "bob@example.com"},
                {"id": "3", "name": "Charlie", "email": "charlie@example.com"},
            ],
        )

        rows = await db.execute("SELECT * FROM users ORDER BY id")
        assert len(rows) == 3

    @pytest.mark.asyncio
    async def test_transaction_commit(self, db):
        """Test transaction commits on success."""
        async with db.transaction():
            await db.execute(
                "INSERT INTO users (id, name, email) VALUES (:id, :name, :email)",
                {"id": "1", "name": "Alice", "email": "alice@example.com"},
            )

        rows = await db.execute("SELECT * FROM users")
        assert len(rows) == 1

    @pytest.mark.asyncio
    async def test_transaction_rollback(self, db):
        """Test transaction rolls back on exception."""
        with pytest.raises(ValueError):
            async with db.transaction():
                await db.execute(
                    "INSERT INTO users (id, name, email) VALUES (:id, :name, :email)",
                    {"id": "1", "name": "Alice", "email": "alice@example.com"},
                )
                raise ValueError("Simulated error")

        rows = await db.execute("SELECT * FROM users")
        assert len(rows) == 0

    @pytest.mark.asyncio
    async def test_empty_result(self, db):
        """Test query with no results."""
        rows = await db.execute("SELECT * FROM users WHERE id = :id", {"id": "999"})
        assert rows == []
