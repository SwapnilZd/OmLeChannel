import json

from src.catalog import VersionedRLOCatalog, parse_versioned_rlo_key, version_sort_key
from src.rlo_schema import RloBatchSearchRequest


class MemoryStorage:
    def __init__(self):
        self.data = {}

    def put(self, key, data):
        self.data[key] = data
        return self.uri(key)

    def uri(self, key):
        return f"memory://{key}"

    def get(self, key):
        try:
            return self.data[key]
        except KeyError:
            raise KeyError(key)

    def list_prefix(self, prefix):
        return sorted(key for key in self.data if key.startswith(prefix))

    def exists(self, key):
        return key in self.data

    def delete(self, key):
        self.data.pop(key, None)


def test_versions_coexist_and_current_is_highest_release():
    catalog = VersionedRLOCatalog(MemoryStorage())
    catalog.put("rlo-1", "1.0.0", json.dumps({"version": "1.0.0"}).encode())
    catalog.put("rlo-1", "2.0.0-beta.1", json.dumps({"version": "2.0.0-beta.1"}).encode())
    catalog.put("rlo-1", "2.0.0", json.dumps({"version": "2.0.0"}).encode())

    assert catalog.versions("rlo-1") == ["2.0.0", "2.0.0-beta.1", "1.0.0"]
    body, version = catalog.get_current("rlo-1")
    assert version == "2.0.0"
    assert json.loads(body)["version"] == "2.0.0"


def test_legacy_document_remains_readable_until_migrated():
    storage = MemoryStorage()
    storage.put("rlo-old.json", b'{"id":"rlo-old"}')
    body, version = VersionedRLOCatalog(storage).get_current("rlo-old")
    assert version is None
    assert json.loads(body)["id"] == "rlo-old"


def test_list_returns_one_current_record_per_logical_rlo():
    catalog = VersionedRLOCatalog(MemoryStorage())
    catalog.put("a", "1.0.0", b"{}")
    catalog.put("a", "1.1.0", b"{}")
    catalog.put("b", "3.0.0", b"{}")
    assert [(item.rlo_id, item.rlo_version) for item in catalog.list_current()] == [
        ("a", "1.1.0"), ("b", "3.0.0")
    ]


def test_batch_search_defaults_to_approved_active_and_is_bounded():
    request = RloBatchSearchRequest.model_validate({
        "queries": [{"query_id": "subject", "text": "leading organizational change"}]
    })
    assert request.queries[0].limit == 10
    assert request.queries[0].filters.statuses == ["approved"]
    assert request.queries[0].filters.active_only is True


def test_version_key_parser_rejects_legacy_and_sort_is_numeric():
    assert parse_versioned_rlo_key("rlo-1.json") is None
    assert parse_versioned_rlo_key("rlos/rlo-1/10.0.0.json") == ("rlo-1", "10.0.0")
    assert version_sort_key("10.0.0") > version_sort_key("2.0.0")
