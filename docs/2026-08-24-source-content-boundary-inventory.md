# Source Content Boundary Inventory

## Upload and storage

- `api/src/source_upload.py` owns validation, checksum deduplication, original
  object writes, and upload/status APIs.
- `api/src/storage.py` resolves the existing object-store implementation.
- Originals are canonical. The current key is
  `source-uploads/{source_id}/original/{filename}`; Phase 2 introduces stable
  source versions and derivative artifact keys without rewriting originals.

## Persistence and workers

- `api/src/source_ingestion/repository.py` currently owns one SQLite job table
  and non-atomic single-process claiming.
- `api/src/source_ingestion/worker.py` currently runs inside the API process and
  extracts only shallow format metadata.
- The Docling/Tesseract runtime is isolated in `source_content/Dockerfile` so
  the heavy worker can be deployed independently.

## RLO catalog and search

- `rlo_schema/v1.py` is the current strict, versioned RLO contract. It enforces
  one enabling objective per RLO and already represents conventional sources,
  but not claim-to-source-node evidence.
- `api/src/catalog.py` and `api/src/app.py` are the versioned RLO catalog write
  boundary. Drafting must call this boundary after validation; it must not write
  storage records directly.
- `api/src/indexer.py` owns RLO embeddings and the `rlos` Qdrant collection.
  Source-node indexing needs its own collection and revision.
- `src/learning_commissioning/adapters/rlo.py` is the compatibility boundary
  between stored RLOs and downstream curriculum assembly.

## Models and access control

- `llm_gateway.ModelAlias` and `litellm/config.yaml` are the only model routing
  boundary. Provider IDs and Azure credentials do not belong in source tools.
- `poc_auth.require_authenticated_request` protects source upload endpoints.
  It authenticates but does not yet establish a learning-admin role.
- Uploaded bytes/text are untrusted content. Deterministic extraction performs
  no model calls; semantic stages must quote bounded node evidence as data and
  prohibit source text from changing instructions or tool policy.
