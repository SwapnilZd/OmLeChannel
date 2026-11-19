from typing import Protocol, runtime_checkable


@runtime_checkable
class StorageBackend(Protocol):
    def uri(self, key: str) -> str:
        """Return the stable object URI for a key without writing it."""
        ...

    def put(self, key: str, data: bytes, content_type: str = "application/json") -> str:
        """Store data at key with its media type. Returns the storage URI."""
        ...

    def get(self, key: str) -> bytes:
        """Retrieve data at key. Raises KeyError if not found."""
        ...

    def list_prefix(self, prefix: str) -> list[str]:
        """Return all keys starting with prefix."""
        ...

    def exists(self, key: str) -> bool:
        """Return True if key exists."""
        ...

    def delete(self, key: str) -> None:
        """Remove key. No-op if key does not exist."""
        ...
