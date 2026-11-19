# Source Content Phase 0 Baseline

Recorded on 2026-08-24 before replacing the metadata-only ingestion worker.

## Repository and containers

- Branch: `feature/source-content-to-rlo`
- Base commit: `89d29182871838540cef01d13c49328db3094621`
- API image: 140,805,424 bytes
- API test image: 152,106,665 bytes
- Docling extraction test image: 1,223,672,808 bytes
- Bundled Docling model artifacts: 669 MB

The extraction image is intentionally separate from the API image. The size is
driven primarily by pinned PyTorch, computer-vision libraries, Heron layout
weights, and TableFormer weights. It must not become the web API runtime.

## Existing observable behavior

`POST /api/source-uploads` accepts PDF, DOCX, PPTX, TXT, Markdown, HTML, and
EPUB files up to 50 MiB, writes the original to object storage, rejects a
duplicate checksum, and creates one SQLite `ingestion_jobs` row. A background
task in the API process claims queued rows and extracts format metadata only.
It does not persist document text, hierarchy, locators, extraction versions,
review state, or evidence.

The feature's first release intentionally narrows full-content extraction to
English PDF and PPTX. Existing upload compatibility is retained until a later
phase explicitly changes it.

## Baseline verification

- API upload/worker and benchmark contract: 20 tests passed.
- Network-isolated Docling runtime proof: 2 tests passed.
- Docling: 2.119.0; PyTorch: 2.7.1; torchvision: 0.22.1.
- Offline proof uses local Heron and TableFormer assets, local Tesseract, remote
  services disabled, external plugins disabled, and model compilation disabled.

## Decisions still open

- Production latency and memory thresholds will be calibrated on both ARM64
  development and the deployment architecture; Phase 0 defines metrics but
  does not invent production numbers from one laptop.
- The current upload repository is SQLite-only. Phase 2 must move durable
  source state to Postgres before adding concurrent workers.
- Existing authentication verifies a POC session but has no learning-admin
  authorization claim. Phase 5 must define and enforce that role boundary.
- Organization-specific legal/security sign-off remains an external release
  gate even though the engineering inventory found no prohibited processing
  API or non-open model weight.
