"""Protocol interfaces for pluggable backends."""

from maven_core.protocols.connector import (
    Connector,
    ConnectorConfig,
    ConnectorCredentials,
    OAuthConnector,
)
from maven_core.protocols.database import Database, Row
from maven_core.protocols.file_store import FileMetadata, FileStore
from maven_core.protocols.kv_store import KVStore
from maven_core.protocols.sandbox import SandboxBackend, SandboxResult

__all__ = [
    "Connector",
    "ConnectorConfig",
    "ConnectorCredentials",
    "Database",
    "FileMetadata",
    "FileStore",
    "KVStore",
    "OAuthConnector",
    "Row",
    "SandboxBackend",
    "SandboxResult",
]
