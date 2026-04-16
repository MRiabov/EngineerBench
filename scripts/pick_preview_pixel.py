from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from shared.workers.schema import RenderBundlePointPickRequest  # noqa: E402
from worker_light.utils.render_query import pick_preview_pixel  # noqa: E402


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Resolve a screen-space pixel against a local render bundle and "
            "print the ray-pick result as JSON."
        )
    )
    parser.add_argument(
        "bundle_path",
        type=str,
        help=("Render bundle path relative to the workspace root."),
    )
    parser.add_argument("--pixel-x", type=int, required=True)
    parser.add_argument("--pixel-y", type=int, required=True)
    parser.add_argument("--image-width", type=int, required=True)
    parser.add_argument("--image-height", type=int, required=True)
    parser.add_argument("--view-index", type=int, default=0)
    parser.add_argument("--orbit-pitch", type=float, default=45.0)
    parser.add_argument("--orbit-yaw", type=float, default=45.0)
    parser.add_argument(
        "--bundle-id",
        type=str,
        default=None,
        help="Optional bundle id to enforce against the resolved manifest.",
    )
    parser.add_argument(
        "--manifest-path",
        type=str,
        default=None,
        help="Optional manifest path for disambiguating the bundle.",
    )
    parser.add_argument(
        "--workspace-root",
        type=Path,
        default=ROOT,
        help="Workspace root used to resolve relative bundle and manifest paths.",
    )
    parser.add_argument(
        "--compact",
        action="store_true",
        help="Print compact JSON instead of pretty-printed JSON.",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    bundle_path = Path(args.bundle_path)
    if bundle_path.is_absolute():
        try:
            bundle_path = bundle_path.relative_to(args.workspace_root)
        except ValueError as exc:
            raise SystemExit(
                "Absolute bundle_path must live inside --workspace-root."
            ) from exc

    request = RenderBundlePointPickRequest(
        bundle_path=str(bundle_path),
        pixel_x=args.pixel_x,
        pixel_y=args.pixel_y,
        image_width=args.image_width,
        image_height=args.image_height,
        orbit_pitch=args.orbit_pitch,
        orbit_yaw=args.orbit_yaw,
        view_index=args.view_index,
        bundle_id=args.bundle_id,
        manifest_path=args.manifest_path,
    )
    result = pick_preview_pixel(
        request,
        workspace_root=args.workspace_root,
    )
    if args.compact:
        print(result.model_dump_json())
    else:
        print(json.dumps(result.model_dump(mode="json"), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
