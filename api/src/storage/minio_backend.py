import io
import os

from minio import Minio
from minio.error import S3Error


class MinioBackend:
    def __init__(self) -> None:
        endpoint = os.environ["MINIO_ENDPOINT"].removeprefix("http://").removeprefix("https://")
        secure = os.environ.get("MINIO_ENDPOINT", "").startswith("https://")
        self._bucket = os.environ["MINIO_BUCKET"]
        self._client = Minio(
            endpoint,
            access_key=os.environ["MINIO_ACCESS_KEY"],
            secret_key=os.environ["MINIO_SECRET_KEY"],
            secure=secure,
        )

    def _ensure_bucket(self) -> None:
        if not self._client.bucket_exists(self._bucket):
            self._client.make_bucket(self._bucket)

    def uri(self, key: str) -> str:
        return f"minio://{self._bucket}/{key}"

    def put(self, key: str, data: bytes, content_type: str = "application/json") -> str:
        self._ensure_bucket()
        self._client.put_object(
            self._bucket,
            key,
            io.BytesIO(data),
            length=len(data),
            content_type=content_type,
        )
        return self.uri(key)

    def get(self, key: str) -> bytes:
        try:
            response = self._client.get_object(self._bucket, key)
            return response.read()
        except S3Error as e:
            if e.code == "NoSuchKey":
                raise KeyError(key) from e
            raise
        finally:
            try:
                response.close()
                response.release_conn()
            except Exception:
                pass

    def list_prefix(self, prefix: str) -> list[str]:
        self._ensure_bucket()
        objects = self._client.list_objects(self._bucket, prefix=prefix, recursive=True)
        return [obj.object_name for obj in objects]

    def exists(self, key: str) -> bool:
        try:
            self._client.stat_object(self._bucket, key)
            return True
        except S3Error:
            return False

    def delete(self, key: str) -> None:
        try:
            self._client.remove_object(self._bucket, key)
        except S3Error:
            pass
