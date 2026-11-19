"""Generate slide illustrations through the LiteLLM image-model alias."""

from __future__ import annotations

import base64
import hashlib
from pathlib import Path

from llm_gateway import ModelAlias, build_langfuse_headers, build_litellm_metadata
from model_gateway import make_openai_client

_ASSETS_DIR = Path("/generated/assets")

# Style prefix appended to every prompt for visual consistency across slides.
_STYLE = (
    "Flat vector illustration, minimal corporate style, clean lines, "
    "professional colour palette, no text or labels, white background."
)


def generate_image(
    prompt: str,
    screen_id: str,
    litellm_base_url: str,
    litellm_api_key: str,
) -> str | None:
    """
    Generate an image for a slide and return a path relative to the output directory.

    Images are cached by a hash of the prompt — identical prompts never hit the API twice.
    Returns None on any failure so the pipeline can continue with a CSS fallback.
    """
    _ASSETS_DIR.mkdir(parents=True, exist_ok=True)

    prompt_hash = hashlib.md5(prompt.encode()).hexdigest()[:10]
    filename = f"{screen_id}-{prompt_hash}.png"
    out_path = _ASSETS_DIR / filename

    if out_path.exists():
        print(f"        [image] cached → {filename}")
        return f"assets/{filename}"

    try:
        client = make_openai_client(
            base_url=litellm_base_url,
            api_key=litellm_api_key,
        )
        response = client.images.generate(
            model=ModelAlias.SLIDE_IMAGE_GENERATION,
            prompt=f"{_STYLE} {prompt}",
            n=1,
            size="1024x1024",
            extra_body={
                "metadata": build_litellm_metadata(
                    ModelAlias.SLIDE_IMAGE_GENERATION,
                    operation="generate",
                    task_id=screen_id,
                )
            },
            extra_headers=build_langfuse_headers(
                ModelAlias.SLIDE_IMAGE_GENERATION,
                operation="generate",
                task_id=screen_id,
            ),
        )
        # LiteLLM image aliases commonly return b64_json by default.
        img_data = response.data[0].b64_json
        if img_data:
            out_path.write_bytes(base64.b64decode(img_data))
            print(f"        [image] generated → {filename}")
            return f"assets/{filename}"
        # Fallback: try URL if b64_json wasn't returned
        img_url = getattr(response.data[0], "url", None)
        if img_url:
            import urllib.request
            urllib.request.urlretrieve(img_url, out_path)
            print(f"        [image] downloaded → {filename}")
            return f"assets/{filename}"
        print(f"        [image] no image data returned for {screen_id}")
        return None
    except Exception as exc:
        print(f"        [image] failed for {screen_id}: {exc}")
        return None
