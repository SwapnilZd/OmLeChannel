import os

from google.cloud import storage
from google.cloud.exceptions import NotFound


class GcsBackend:
    def __init__(self) -> None:
        self._bucket_name = os.environ["GCS_BUCKET"]
        self._client = storage.Client()  # uses ADC automatically
        self._bucket = self._client.bucket(self._bucket_name)

    def uri(self, key: str) -> str:
        return f"gs://{self._bucket_name}/{key}"

    def put(self, key: str, data: bytes, content_type: str = "application/json") -> str:
        blob = self._bucket.blob(key)
        blob.upload_from_string(data, content_type=content_type)
        return self.uri(key)

    def get(self, key: str) -> bytes:
        blob = self._bucket.blob(key)
        try:
            return blob.download_as_bytes()
        except NotFound:
            raise KeyError(key)

    def list_prefix(self, prefix: str) -> list[str]:
        blobs = self._client.list_blobs(self._bucket_name, prefix=prefix)
        return [blob.name for blob in blobs]

    def exists(self, key: str) -> bool:
        return self._bucket.blob(key).exists()

    def delete(self, key: str) -> None:
        blob = self._bucket.blob(key)
        try:
            blob.delete()
        except NotFound:
            pass
