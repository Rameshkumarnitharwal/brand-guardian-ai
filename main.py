"""CLI: python main.py <youtube_url | local_video_path> [--output report.json]"""

import argparse
import json
import logging
import sys
from pathlib import Path

from brand_guardian.graph import run_audit

SEVERITY_ICON = {"CRITICAL": "🔴", "HIGH": "🟠", "MEDIUM": "🟡", "LOW": "🔵"}


def print_report(report: dict) -> None:
    print(f"\n=== Brand Guardian Compliance Report ===")
    print(f"Video:  {report['video_url']}")
    print(f"Status: {report['status']}")
    print(f"\n{report['summary']}\n")
    for i, v in enumerate(report["violations"], 1):
        print(f"{i}. {SEVERITY_ICON.get(v['severity'], '')} [{v['severity']}] {v['category']} @ {v.get('timestamp') or 'n/a'}")
        print(f"   Claim:  \"{v['claim']}\"")
        print(f"   Rule:   {v['rule_reference']}")
        print(f"   Why:    {v['explanation']}")
        print(f"   Fix:    {v['recommendation']}\n")
    if not report["violations"]:
        print("No violations found.")


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit a video for advertising compliance.")
    parser.add_argument("video", help="YouTube URL or path to a local video file")
    parser.add_argument("-o", "--output", type=Path, help="Write the JSON report to this file")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    final = run_audit(args.video)
    if final.get("errors"):
        print("Audit failed:", *final["errors"], sep="\n  - ", file=sys.stderr)
        return 1

    report = final["report"]
    print_report(report)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2))
        print(f"Report written to {args.output}")
    return 2 if report["status"] == "FAIL" else 0


if __name__ == "__main__":
    sys.exit(main())
