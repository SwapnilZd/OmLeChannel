import json
from types import SimpleNamespace

from src import app


class MemoryStorage:
    def __init__(self, keys=()):
        self.keys = set(keys)

    def list_prefix(self, prefix):
        return sorted(key for key in self.keys if key.startswith(prefix))

    def uri(self, key):
        return f"memory://{key}"


class FakeIndexer:
    def __init__(self, current=()):
        self.current = set(current)
        self.upserts = []
        self.activations = []

    def is_index_current(self, rlo_id, rlo_version):
        return (rlo_id, rlo_version) in self.current

    def upsert(self, rlo, storage_uri, *, is_active):
        self.upserts.append((rlo.id, rlo.version, storage_uri, is_active))
        return True

    def set_active_version(self, rlo_id, rlo_version):
        self.activations.append((rlo_id, rlo_version))


def test_startup_seed_ingests_missing_version_when_catalog_is_not_empty(tmp_path, monkeypatch):
    existing = {"id": "rlo-existing", "version": "1.0.0"}
    added = {"id": "rlo-new", "version": "1.0.0"}
    (tmp_path / "existing.json").write_text(json.dumps(existing))
    (tmp_path / "new.json").write_text(json.dumps(added))

    monkeypatch.setattr(app, "SEED_DIR", str(tmp_path))
    monkeypatch.setattr(
        app,
        "_storage",
        MemoryStorage({"rlos/rlo-existing/1.0.0.json"}),
    )
    indexer = FakeIndexer({("rlo-existing", "1.0.0")})
    monkeypatch.setattr(app, "_indexer", indexer)
    monkeypatch.setattr(
        app,
        "validate_rlo",
        lambda raw: (SimpleNamespace(id=raw["id"], version=raw["version"]), "1.0.0"),
    )

    ingested = []

    def fake_ingest(body):
        raw = json.loads(body)
        ingested.append(raw["id"])
        return SimpleNamespace(rlo_id=raw["id"], indexed=True)

    monkeypatch.setattr(app, "_ingest", fake_ingest)

    app._seed_missing()

    assert ingested == ["rlo-new"]
    assert indexer.upserts == []


def test_startup_seed_repairs_an_existing_version_missing_from_index(tmp_path, monkeypatch):
    existing = {"id": "rlo-raci", "version": "1.0.0"}
    (tmp_path / "raci.json").write_text(json.dumps(existing))
    monkeypatch.setattr(app, "SEED_DIR", str(tmp_path))
    monkeypatch.setattr(
        app,
        "_storage",
        MemoryStorage({"rlos/rlo-raci/1.0.0.json"}),
    )
    indexer = FakeIndexer()
    monkeypatch.setattr(app, "_indexer", indexer)
    monkeypatch.setattr(
        app,
        "validate_rlo",
        lambda raw: (SimpleNamespace(id=raw["id"], version=raw["version"]), "1.0.0"),
    )

    app._seed_missing()

    assert indexer.upserts == [
        ("rlo-raci", "1.0.0", "memory://rlos/rlo-raci/1.0.0.json", True)
    ]
    assert indexer.activations == [("rlo-raci", "1.0.0")]
