from __future__ import annotations

import argparse
import json
import logging
import sys

from monitor_uaf.pipeline import MonitorPipeline, render_only


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Monitor legislativo estratégico para la UAF")
    parser.add_argument("--no-email", action="store_true", help="Ejecuta el barrido sin enviar correos")
    parser.add_argument("--render-only", action="store_true", help="Regenera el dashboard con los JSON existentes")
    parser.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )
    if args.render_only:
        path = render_only()
        print(f"Dashboard generado: {path}")
        return 0
    status = MonitorPipeline().run(no_email=args.no_email)
    print(json.dumps(status, ensure_ascii=False, indent=2))
    all_failed = status.get("sources") and not any(item.get("ok") for item in status["sources"].values())
    return 2 if all_failed else 0


if __name__ == "__main__":
    sys.exit(main())
