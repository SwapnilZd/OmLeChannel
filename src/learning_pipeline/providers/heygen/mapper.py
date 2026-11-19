"""HeyGenSceneMapper — pure, deterministic, side-effect free.

Responsibilities:
  - Clean avatar scripts.
  - Map a provider-neutral AvatarVideoRenderInput to a HeyGenCreateVideoRequest.

Non-responsibilities (must not be added here):
  - Reading environment variables.
  - Uploading files to HeyGen.
  - Making any network call.
  - Reading or writing artifacts.
  - Resolving repository-root-relative paths.
  - Polling for status.
"""
from __future__ import annotations

import re
import logging
from typing import TYPE_CHECKING

from learning_pipeline.providers.heygen.models import (
    HeyGenAvatarCharacter,
    HeyGenColorBackground,
    HeyGenCreateVideoRequest,
    HeyGenDimension,
    HeyGenImageBackground,
    HeyGenVideoInputScene,
    HeyGenVoiceInput,
)

if TYPE_CHECKING:
    from learning_pipeline.tools.avatar_video.contracts import (
        AvatarVideoRenderInput,
        AvatarVideoScene,
        ImageBackground,
        SolidColorBackground,
        VideoBackground,
    )
    from learning_pipeline.tools.avatar_video.profiles import (
        HeyGenAvatarProfile,
        HeyGenVoiceProfile,
    )

logger = logging.getLogger(__name__)

# Control characters except horizontal tab (\x09) and CR/LF
_CONTROL_CHAR_RE = re.compile(r"[\x00-\x08\x0B-\x1F\x7F]")
_WHITESPACE_RE = re.compile(r"\s*\r?\n+\s*")
_DASH_RE = re.compile(r"[–—]+")
_MULTI_SPACE_RE = re.compile(r"\s{2,}")


def clean_script(text: str) -> str:
    """Sanitise avatar script text before sending to HeyGen.

    Removes control characters, collapses newlines to spaces,
    normalises em/en dashes, and collapses multiple spaces.
    Returns an empty string for empty input.
    """
    if not text:
        return ""
    text = _CONTROL_CHAR_RE.sub("", text)
    text = _WHITESPACE_RE.sub(" ", text)
    text = _DASH_RE.sub(" — ", text)
    text = _MULTI_SPACE_RE.sub(" ", text)
    return text.strip()


class HeyGenSceneMapper:
    """Map a provider-neutral render request to a HeyGen API payload.

    This class is stateless and has no external dependencies.
    All inputs (resolved asset IDs, avatar/voice profiles) must be
    provided by the caller.

    Parameters
    ----------
    unsupported_background_policy:
        What to do when a VideoBackground is encountered.
        ``"error"`` raises ValueError (default); ``"color_fallback"`` replaces
        with the solid-color fallback.
    fallback_color:
        Hex color to use when a background cannot be rendered.
    """

    def __init__(
        self,
        *,
        unsupported_background_policy: str = "error",
        fallback_color: str = "#1A1A2E",
    ) -> None:
        self._unsupported_policy = unsupported_background_policy
        self._fallback_color = fallback_color

    def map_request(
        self,
        request: "AvatarVideoRenderInput",
        resolved_assets: dict[str, str],
        avatar_profile: "HeyGenAvatarProfile",
        voice_profile: "HeyGenVoiceProfile",
    ) -> HeyGenCreateVideoRequest:
        """Produce a HeyGenCreateVideoRequest from a provider-neutral input.

        Parameters
        ----------
        request:
            The validated, provider-neutral render input.
        resolved_assets:
            Mapping of artifact_uri → HeyGen asset_id for image/video
            backgrounds.  The executor is responsible for uploading the
            assets before calling this method.
        avatar_profile:
            Resolved HeyGen avatar configuration.
        voice_profile:
            Resolved HeyGen voice configuration.

        Returns
        -------
        HeyGenCreateVideoRequest
            A fully typed, wire-format-ready HeyGen request.

        Raises
        ------
        ValueError
            If any scene has an empty script after cleaning, or if a
            VideoBackground is used with ``unsupported_background_policy="error"``.
        """
        scenes = tuple(
            self._map_scene(scene, resolved_assets, avatar_profile, voice_profile)
            for scene in request.scenes
        )
        return HeyGenCreateVideoRequest(
            video_inputs=scenes,
            dimension=HeyGenDimension(
                width=request.dimensions.width,
                height=request.dimensions.height,
            ),
            caption=request.captions,
        )

    def _map_scene(
        self,
        scene: "AvatarVideoScene",
        resolved_assets: dict[str, str],
        avatar_profile: "HeyGenAvatarProfile",
        voice_profile: "HeyGenVoiceProfile",
    ) -> HeyGenVideoInputScene:
        script = clean_script(scene.script)
        if not script:
            raise ValueError(
                f"Scene {scene.scene_id!r}: script is empty after cleaning."
            )

        voice_speed = scene.voice_speed if hasattr(scene, "voice_speed") else voice_profile.default_speed

        return HeyGenVideoInputScene(
            character=HeyGenAvatarCharacter(
                avatar_id=avatar_profile.avatar_id,
                avatar_style=avatar_profile.avatar_style,
            ),
            voice=HeyGenVoiceInput(
                input_text=script,
                voice_id=voice_profile.voice_id,
                speed=voice_speed,
            ),
            background=self._map_background(scene, resolved_assets),
        )

    def _map_background(
        self,
        scene: "AvatarVideoScene",
        resolved_assets: dict[str, str],
    ) -> "HeyGenColorBackground | HeyGenImageBackground":
        bg = scene.background

        from learning_pipeline.tools.avatar_video.contracts import (
            SolidColorBackground,
            ImageBackground,
            VideoBackground,
        )

        if isinstance(bg, SolidColorBackground):
            return HeyGenColorBackground(value=bg.color)

        if isinstance(bg, ImageBackground):
            asset_id = resolved_assets.get(bg.artifact_uri)
            if not asset_id:
                raise ValueError(
                    f"Scene {scene.scene_id!r}: no resolved asset_id for "
                    f"image background {bg.artifact_uri!r}. "
                    "Ensure the asset was uploaded before calling map_request()."
                )
            return HeyGenImageBackground(image_asset_id=asset_id)

        if isinstance(bg, VideoBackground):
            if self._unsupported_policy == "error":
                raise ValueError(
                    f"Scene {scene.scene_id!r}: VideoBackground is not supported "
                    "by the HeyGen provider adapter in this version. "
                    "Use SolidColorBackground or ImageBackground instead."
                )
            # color_fallback
            logger.warning(
                "Scene %r: VideoBackground replaced with color fallback %r",
                scene.scene_id,
                self._fallback_color,
            )
            return HeyGenColorBackground(value=self._fallback_color)

        raise ValueError(
            f"Scene {scene.scene_id!r}: unrecognised background type {type(bg).__name__!r}"
        )
