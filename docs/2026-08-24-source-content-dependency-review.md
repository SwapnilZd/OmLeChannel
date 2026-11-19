# Source Extraction Dependency and Model Review

## Candidate selected for implementation

- Python 3.12 slim container
- Docling 2.119.0 (MIT project)
- PyTorch 2.7.1 and torchvision 0.22.1 (BSD)
- Tesseract 5.5 with English data (Apache-2.0)
- Docling Heron layout weights (Apache-2.0)
- Docling TableFormer weights from `docling-models` v2.3.0
  (CDLA-Permissive-2.0)

The image downloads weights only at build time. Runtime sets Hugging Face and
Transformers offline modes, disables Docling remote services and external
plugins, and was exercised under Compose `network_mode: none`.

## Inventory result

`pip-licenses` reported 105 installed Python distributions. Declared licenses
are MIT, BSD, Apache-2.0, ISC, PSF, MPL-2.0, or compatible dual-license
combinations. It found no GPL, AGPL, SSPL, proprietary package, or remote
document-processing SDK. Thirty-five modern packages expose incomplete license
classifier metadata and were reported as `UNKNOWN`; this includes Docling
packages whose upstream project files declare MIT. That scanner result is a
metadata limitation, not approval by omission.

The bundled model cards are retained in `/opt/docling-models` and explicitly
declare Apache-2.0 for Heron and CDLA-Permissive-2.0 for TableFormer. The image
also contains dynamically linked Debian runtime libraries needed by Tesseract
and OpenCV. Their notices must be included in the normal container software
bill of materials.

## Engineering disposition

Approved as the pinned implementation candidate: all core extraction code and
model weights are open source under permissive terms, processing is local, and
the isolated runtime proof passes. Before production distribution, regenerate
the package/container SBOM and submit it through Deloitte's standard legal and
security approval process. A dependency version change invalidates this review
and requires the proof and inventory to be rerun.
