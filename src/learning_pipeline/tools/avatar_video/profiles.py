"""Logical avatar and voice profile registry for the HeyGen provider.

Logical profiles such as ``default_instructor`` decouple BuildPlan content
from provider-specific IDs.  Provider IDs are deployment configuration that
lives outside the BuildPlan.

Profile resolution order:
1. Explicit profiles passed to HeyGenProfileRegistry constructor.
2. Environment variables read at worker startup (via load_profile_settings()).

Environment variables (real mode only):
    HEYGEN_AVATAR_PROFILE_{PROFILE_UPPER}_ID
    HEYGEN_AVATAR_PROFILE_{PROFILE_UPPER}_STYLE   (default: "normal")
    HEYGEN_VOICE_PROFILE_{PROFILE_UPPER}_ID
    HEYGEN_VOICE_PROFILE_{PROFILE_UPPER}_SPEED    (default: "1.0")

Example — configuring the default_instructor profile:
    HEYGEN_AVATAR_PROFILE_DEFAULT_INSTRUCTOR_ID=Annie_expressive_public
    HEYGEN_VOICE_PROFILE_DEFAULT_INSTRUCTOR_ID=330290724a1b470fb63153f34d4c0183

Profiles registered here must NOT be exposed in the planner-safe manifest.
"""
from __future__ import annotations

import os

from learning_pipeline.contracts.common import FrozenModel
from learning_pipeline.tools.errors import MissingRealModeConfigError


class HeyGenAvatarProfile(FrozenModel):
    profile: str
    avatar_id: str
    avatar_style: str = "normal"


class HeyGenVoiceProfile(FrozenModel):
    profile: str
    voice_id: str
    default_speed: float = 1.0


class HeyGenProfileRegistry:
    """Resolves logical profile names to HeyGen provider IDs.

    Parameters
    ----------
    avatar_profiles:
        Mapping of logical profile name → HeyGenAvatarProfile.
    voice_profiles:
        Mapping of logical profile name → HeyGenVoiceProfile.
    """

    def __init__(
        self,
        avatar_profiles: dict[str, HeyGenAvatarProfile],
        voice_profiles: dict[str, HeyGenVoiceProfile],
    ) -> None:
        self._avatars = dict(avatar_profiles)
        self._voices = dict(voice_profiles)

    def resolve_avatar(self, profile: str) -> HeyGenAvatarProfile:
        result = self._avatars.get(profile)
        if result is None:
            raise MissingRealModeConfigError(
                f"No HeyGen avatar profile configured for {profile!r}. "
                f"Available profiles: {sorted(self._avatars)}. "
                "Set HEYGEN_AVATAR_PROFILE_{PROFILE_UPPER}_ID in the environment."
            )
        return result

    def resolve_voice(self, profile: str) -> HeyGenVoiceProfile:
        result = self._voices.get(profile)
        if result is None:
            raise MissingRealModeConfigError(
                f"No HeyGen voice profile configured for {profile!r}. "
                f"Available profiles: {sorted(self._voices)}. "
                "Set HEYGEN_VOICE_PROFILE_{PROFILE_UPPER}_ID in the environment."
            )
        return result

    @property
    def avatar_profile_names(self) -> frozenset[str]:
        return frozenset(self._avatars)

    @property
    def voice_profile_names(self) -> frozenset[str]:
        return frozenset(self._voices)


# ── Environment-based profile loading ─────────────────────────────────────────

_KNOWN_PROFILES = ("default_instructor", "default_narrator")

# Public fallback defaults used in fake mode and tests.
_FAKE_AVATAR_ID = "Annie_expressive_public"
_FAKE_VOICE_ID = "330290724a1b470fb63153f34d4c0183"


def load_profile_settings() -> HeyGenProfileRegistry:
    """Build a HeyGenProfileRegistry from environment variables.

    For each profile in _KNOWN_PROFILES, reads:
        HEYGEN_AVATAR_PROFILE_{UPPER_PROFILE}_ID
        HEYGEN_AVATAR_PROFILE_{UPPER_PROFILE}_STYLE   (default: "normal")
        HEYGEN_VOICE_PROFILE_{UPPER_PROFILE}_ID
        HEYGEN_VOICE_PROFILE_{UPPER_PROFILE}_SPEED    (default: "1.0")

    Profiles whose ID env vars are absent are silently skipped.
    Resolution failure raises MissingRealModeConfigError at call time.
    """
    avatar_profiles: dict[str, HeyGenAvatarProfile] = {}
    voice_profiles: dict[str, HeyGenVoiceProfile] = {}

    for name in _KNOWN_PROFILES:
        upper = name.upper().replace("-", "_")

        avatar_id = os.getenv(f"HEYGEN_AVATAR_PROFILE_{upper}_ID", "").strip()
        if avatar_id:
            avatar_profiles[name] = HeyGenAvatarProfile(
                profile=name,
                avatar_id=avatar_id,
                avatar_style=os.getenv(
                    f"HEYGEN_AVATAR_PROFILE_{upper}_STYLE", "normal"
                ).strip(),
            )

        voice_id = os.getenv(f"HEYGEN_VOICE_PROFILE_{upper}_ID", "").strip()
        if voice_id:
            raw_speed = os.getenv(f"HEYGEN_VOICE_PROFILE_{upper}_SPEED", "1.0").strip()
            voice_profiles[name] = HeyGenVoiceProfile(
                profile=name,
                voice_id=voice_id,
                default_speed=float(raw_speed),
            )

    return HeyGenProfileRegistry(
        avatar_profiles=avatar_profiles,
        voice_profiles=voice_profiles,
    )


def build_fake_profile_registry() -> HeyGenProfileRegistry:
    """Return a registry with deterministic fake profiles for test/fake mode."""
    avatar = HeyGenAvatarProfile(
        profile="default_instructor",
        avatar_id=_FAKE_AVATAR_ID,
        avatar_style="normal",
    )
    voice = HeyGenVoiceProfile(
        profile="default_instructor",
        voice_id=_FAKE_VOICE_ID,
        default_speed=1.0,
    )
    return HeyGenProfileRegistry(
        avatar_profiles={
            "default_instructor": avatar,
            "default_narrator": avatar,
        },
        voice_profiles={
            "default_instructor": voice,
            "default_narrator": voice,
        },
    )
