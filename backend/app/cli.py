"""SARVEX command-line interface.

Usage (from backend/):
    python -m app.cli doctor
    python -m app.cli model list
    python -m app.cli train hfce --n-samples 1000
    python -m app.cli rag test --query "interferometric phase"
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent


def cmd_doctor(args) -> int:
    import os

    checks = {}
    try:
        import rasterio

        checks["rasterio"] = rasterio.__version__
    except Exception as e:  # noqa: BLE001
        checks["rasterio"] = f"MISSING: {e}"
    try:
        import xgboost

        checks["xgboost"] = xgboost.__version__
    except Exception as e:  # noqa: BLE001
        checks["xgboost"] = f"MISSING: {e}"
    try:
        import shap

        checks["shap"] = shap.__version__
    except Exception as e:  # noqa: BLE001
        checks["shap"] = f"MISSING: {e}"
    # DB
    try:
        sys.path.insert(0, str(BACKEND_DIR))
        from app.config import get_settings

        s = get_settings()
        checks["database_url"] = s.resolved_database_url.split("@")[-1] if "@" in s.resolved_database_url else s.resolved_database_url
        checks["demo_mode"] = s.demo_mode
        checks["offline_mode"] = s.offline_mode
    except Exception as e:  # noqa: BLE001
        checks["config"] = f"ERROR: {e}"
    print(json.dumps(checks, indent=2))
    return 0


def cmd_model_list(args) -> int:
    sys.path.insert(0, str(BACKEND_DIR))
    from app.ml.registry import get_model_registry

    reg = get_model_registry()
    for spec in reg.all_specs():
        print(f"{spec.category:20s} {spec.name:32s} {spec.version:8s} {spec.provider:16s} default={spec.is_default}")
    return 0


def cmd_train_hfce(args) -> int:
    script = BACKEND_DIR / "scripts" / "train_sarvex_hfce.py"
    cmd = [sys.executable, str(script), "--n-samples", str(args.n_samples), "--output", args.output, "--seed", str(args.seed)]
    return subprocess.run(cmd, cwd=str(BACKEND_DIR)).returncode


def cmd_rag_test(args) -> int:
    sys.path.insert(0, str(BACKEND_DIR))
    from app.db.session import session_scope
    from app.rag.retrieval import retrieve

    with session_scope() as session:
        chunks, _meta = retrieve(session, args.query, top_k=args.top_k)
        for r in chunks:
            print(f"{r.score:.3f}  {r.title}  [{r.section}]")
    return 0


def cmd_demo(args) -> int:
    sys.path.insert(0, str(BACKEND_DIR))
    from app.db.session import session_scope
    from app.services.demo import seed_demo

    with session_scope() as session:
        summary = seed_demo(session, include_analyses=True)
        print(json.dumps({k: (v if not isinstance(v, (list, dict)) else len(v)) for k, v in summary.items()}, indent=2))
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="sarvex")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("doctor")
    p.set_defaults(func=cmd_doctor)

    p = sub.add_parser("model")
    p.add_argument("action", choices=["list"])
    p.set_defaults(func=cmd_model_list)

    p = sub.add_parser("train")
    p.add_argument("target", choices=["hfce"])
    p.add_argument("--n-samples", type=int, default=1000)
    p.add_argument("--output", default="artifacts/models/hfce")
    p.add_argument("--seed", type=int, default=42)
    p.set_defaults(func=cmd_train_hfce)

    p = sub.add_parser("rag")
    p.add_argument("action", choices=["test"])
    p.add_argument("--query", required=True)
    p.add_argument("--top-k", type=int, default=5)
    p.set_defaults(func=cmd_rag_test)

    p = sub.add_parser("demo")
    p.set_defaults(func=cmd_demo)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
PY