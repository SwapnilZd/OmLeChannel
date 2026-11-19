"""Evaluate semantic catalog retrieval against a small human-judged set."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any

import httpx


async def evaluate(catalog_url: str, judgments: list[dict[str, Any]], status: str) -> dict[str, Any]:
    rows = []
    score_samples = {label: [] for label in ("expected", "acceptable", "weak", "forbidden")}
    async with httpx.AsyncClient(timeout=30) as client:
        for offset in range(0, len(judgments), 4):
            chunk = judgments[offset:offset + 4]
            payload = {"queries": [
                {
                    "query_id": f"judgment-{offset + index}",
                    "text": item["request"],
                    "limit": 10,
                    "filters": {"statuses": [status], "active_only": True},
                }
                for index, item in enumerate(chunk)
            ]}
            response = await client.post(
                f"{catalog_url.rstrip('/')}/api/rlo-search/batch", json=payload
            )
            response.raise_for_status()
            for item, result in zip(chunk, response.json()["results"], strict=True):
                hits = result["hits"]
                score_by_id = {hit["rlo_id"]: hit["score"] for hit in hits}
                rank_by_id = {hit["rlo_id"]: rank for rank, hit in enumerate(hits, start=1)}
                for label in score_samples:
                    score_samples[label].extend(
                        score_by_id[rlo_id]
                        for rlo_id in item[label]
                        if rlo_id in score_by_id
                    )
                rows.append({
                    "request": item["request"],
                    "expected_ranks": {
                        rlo_id: rank_by_id.get(rlo_id) for rlo_id in item["expected"]
                    },
                    "forbidden_hits": [
                        rlo_id for rlo_id in item["forbidden"] if rlo_id in rank_by_id
                    ],
                    "top_five": [
                        {"rlo_id": hit["rlo_id"], "score": round(hit["score"], 4)}
                        for hit in hits[:5]
                    ],
                })
    expected_total = sum(len(item["expected"]) for item in judgments)
    expected_found = sum(
        rank is not None for row in rows for rank in row["expected_ranks"].values()
    )
    return {
        "status_filter": status,
        "expected_recall_at_10": expected_found / expected_total if expected_total else None,
        "score_samples": {
            label: {
                "count": len(scores),
                "minimum": min(scores) if scores else None,
                "maximum": max(scores) if scores else None,
                "mean": sum(scores) / len(scores) if scores else None,
            }
            for label, scores in score_samples.items()
        },
        "rows": rows,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("judgments", type=Path)
    parser.add_argument("--catalog-url", default="http://api:8000")
    parser.add_argument("--status", default="approved")
    args = parser.parse_args()
    judgments = json.loads(args.judgments.read_text(encoding="utf-8"))
    print(json.dumps(asyncio.run(evaluate(args.catalog_url, judgments, args.status)), indent=2))


if __name__ == "__main__":
    main()
