#!/usr/bin/env python3
"""Build index.json from all hub manifests.

Output shape:
  {
    "schema_version": 1,
    "hub_version": "<from --version>",
    "generated_at": "<ISO 8601 UTC>",
    "items": [
      {"id": "...", "category": "model|assistant|mcp-server", "name": "...",
       "summary": "...", "tags": [...], "verified": bool, "added_at": "YYYY-MM-DD",
       "min_ziee_version": "x.y.z" | null, "manifest_path": "models/foo.yaml"}
    ]
  }

The bundle tarball is built separately by the workflow (`tar czf ...`); this
script only produces index.json.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

try:
    import yaml  # type: ignore
except ImportError:
    sys.exit("pyyaml is required (pip install pyyaml)")

CATEGORIES = [
    ("model", "models"),
    ("assistant", "assistants"),
    ("mcp-server", "mcp-servers"),
]


def summarize(description: str) -> str:
    line = description.splitlines()[0].strip() if description else ""
    return line[:200]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument("--version", required=True, help="hub release version (e.g. 0.1.0)")
    parser.add_argument("--out", required=True, help="output path for index.json")
    args = parser.parse_args()
    repo = Path(args.repo).resolve()

    items: list[dict] = []
    for category, folder in CATEGORIES:
        for path in sorted((repo / folder).glob("*.yaml")):
            with path.open("r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            hub_meta = data.get("hub_metadata") or {}
            items.append({
                "id": data["id"],
                "category": category,
                "name": data.get("display_name") or data.get("name") or data["id"],
                "summary": summarize(data.get("description", "")),
                "tags": data.get("tags") or [],
                "verified": bool(hub_meta.get("verified")),
                "added_at": hub_meta.get("added_at"),
                "min_ziee_version": hub_meta.get("min_ziee_version"),
                "manifest_path": str(path.relative_to(repo)),
            })

    items.sort(key=lambda it: (it["category"], it["id"]))
    payload = {
        "schema_version": 1,
        "hub_version": args.version,
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "items": items,
    }
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2, sort_keys=False) + "\n", encoding="utf-8")
    print(f"wrote {out_path} with {len(items)} items (hub_version={args.version})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
