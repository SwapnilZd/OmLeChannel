"""Typed pricing configuration for HeyGen avatar-video rendering.

Pricing values come from explicit configuration — never from hard-coded
assumptions.  When pricing is unknown, cost is reported as None rather
than a fabricated value.

The values documented here are observational and must be verified against
current official HeyGen pricing before production deployment.
"""
from __future__ import annotations

import os

from learning_pipeline.contracts.common import FrozenModel


class HeyGenPricingConfig(FrozenModel):
    """Typed pricing configuration for one HeyGen engine tier.

    All monetary values are in USD.  Credit-to-USD conversion and per-second
    rates depend on the HeyGen subscription and engine in use.
    """

    pricing_version: str
    engine: str
    credits_per_video_second: float | None = None
    credits_per_asset_upload: float | None = None
    usd_per_credit: float | None = None

    def estimate_credits(
        self,
        *,
        duration_seconds: float | None,
        upload_count: int,
    ) -> float | None:
        """Return estimated total credits, or None if pricing is unavailable."""
        if self.credits_per_video_second is None:
            return None
        video_credits = (duration_seconds or 0.0) * self.credits_per_video_second
        upload_credits = (
            (upload_count * self.credits_per_asset_upload)
            if self.credits_per_asset_upload is not None
            else 0.0
        )
        return round(video_credits + upload_credits, 4)

    def estimate_cost_usd(
        self,
        *,
        duration_seconds: float | None,
        upload_count: int,
    ) -> float | None:
        """Return estimated total cost in USD, or None if pricing is unavailable."""
        credits = self.estimate_credits(
            duration_seconds=duration_seconds,
            upload_count=upload_count,
        )
        if credits is None or self.usd_per_credit is None:
            return None
        return round(credits * self.usd_per_credit, 4)


# ── Default observational pricing (Avatar III v3) ─────────────────────────────
# Source: dashboard observation, June 2024.
# Verify against current official HeyGen pricing before production use.

DEFAULT_PRICING = HeyGenPricingConfig(
    pricing_version="2024-06-observational",
    engine="avatar_iii_v3",
    credits_per_video_second=0.0167,
    credits_per_asset_upload=None,  # not officially documented
    usd_per_credit=1.0,
)


def load_pricing_config() -> HeyGenPricingConfig:
    """Build a HeyGenPricingConfig from environment variables.

    Falls back to DEFAULT_PRICING for any value not explicitly set.

    Environment variables:
        HEYGEN_PRICING_VERSION           — default: "2024-06-observational"
        HEYGEN_PRICING_ENGINE            — default: "avatar_iii_v3"
        HEYGEN_CREDITS_PER_VIDEO_SECOND  — default: "0.0167"
        HEYGEN_CREDITS_PER_ASSET_UPLOAD  — default: unset (None)
        HEYGEN_USD_PER_CREDIT            — default: "1.0"
    """
    def _float_or_none(key: str, default: float | None) -> float | None:
        raw = os.getenv(key, "").strip()
        if not raw:
            return default
        return float(raw)

    return HeyGenPricingConfig(
        pricing_version=os.getenv(
            "HEYGEN_PRICING_VERSION",
            DEFAULT_PRICING.pricing_version,
        ).strip(),
        engine=os.getenv(
            "HEYGEN_PRICING_ENGINE",
            DEFAULT_PRICING.engine,
        ).strip(),
        credits_per_video_second=_float_or_none(
            "HEYGEN_CREDITS_PER_VIDEO_SECOND",
            DEFAULT_PRICING.credits_per_video_second,
        ),
        credits_per_asset_upload=_float_or_none(
            "HEYGEN_CREDITS_PER_ASSET_UPLOAD",
            DEFAULT_PRICING.credits_per_asset_upload,
        ),
        usd_per_credit=_float_or_none(
            "HEYGEN_USD_PER_CREDIT",
            DEFAULT_PRICING.usd_per_credit,
        ),
    )
