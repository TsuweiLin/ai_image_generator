#!/usr/bin/env python3
"""Resumable batch runner for the local Lovart skill.

This file deliberately shells out to agent_skill.py.  It does not call Lovart
HTTP endpoints directly, which is a requirement of the Lovart skill.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parent
SKILL = ROOT / "lovart-skill" / "lovart-skill" / "agent_skill.py"
DEFAULT_PROMPT = ROOT / "通用prompt.txt"
DEFAULT_MUSIC = ROOT / "音樂素材" / "鄉村風.mp3"
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff"}


def load_dotenv(path: Path) -> None:
    """Load simple KEY=VALUE entries without adding a third-party dependency.

    Existing shell variables win over values in .env, which makes CI and
    temporary credential overrides safe.
    """
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        if key in {"LOVART_ACCESS_KEY", "LOVART_SECRET_KEY"}:
            os.environ.setdefault(key, value)


def now() -> str:
  return datetime.now(timezone.utc).isoformat()


def run_skill(args: list[str], *, retries: int = 3) -> object:
  """Run an allowed skill command and decode its JSON response."""
  cmd = [sys.executable, str(SKILL), *args]
  last = ""
  for attempt in range(1, retries + 1):
    proc = subprocess.run(cmd, cwd=ROOT, text=True, capture_output=True)
    last = (proc.stdout or "") + (proc.stderr or "")
    if proc.returncode == 0:
      try:
        return json.loads(proc.stdout)
      except json.JSONDecodeError:
        return {"raw": proc.stdout}
    if attempt < retries:
      time.sleep(min(10 * attempt, 30))
  raise RuntimeError(f"Lovart command failed: {' '.join(args)}\n{last[-3000:]}")


def sha256(path: Path) -> str:
  h = hashlib.sha256()
  with path.open("rb") as f:
    for block in iter(lambda: f.read(1024 * 1024), b""):
      h.update(block)
  return h.hexdigest()


def load_json(path: Path, default: object) -> object:
  if not path.exists():
    return default
  return json.loads(path.read_text(encoding="utf-8"))


def save_json(path: Path, value: object) -> None:
  path.parent.mkdir(parents=True, exist_ok=True)
  tmp = path.with_suffix(path.suffix + ".tmp")
  tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
  tmp.replace(path)


def product_dirs(products_root: Path) -> list[Path]:
  return sorted(p for p in products_root.iterdir() if p.is_dir() and not p.name.startswith("."))


def images_for(product: Path) -> list[Path]:
  return sorted(p for p in product.iterdir() if p.is_file() and p.suffix.lower() in IMAGE_EXTS)


def upload_cached(path: Path, cache: dict, dry_run: bool) -> str:
  key = sha256(path)
  if key in cache:
    return cache[key]
  if dry_run:
    return f"DRY_RUN:{path.name}"
  result = run_skill(["upload", "--file", str(path)])
  if not isinstance(result, dict) or not result.get("url"):
    raise RuntimeError(f"Upload response did not contain url for {path}: {result}")
  cache[key] = result["url"]
  return result["url"]


def setup(project_id: str | None, project_name: str, mode: str, dry_run: bool) -> dict:
  if dry_run:
    return {"active_project": project_id or "DRY_RUN_PROJECT"}
  # Required by the skill before the first generation, in this order.
  config = run_skill(["config", "--json"])
  active = config.get("active_project") if isinstance(config, dict) else None
  if not active:
    if not project_id:
      raise RuntimeError("No active Lovart project. Re-run with --project-id PROJECT_ID.")
    run_skill(["project-add", "--project-id", project_id, "--name", project_name])
    active = project_id
  # Required state check before the first chat. Existing threads are not reused:
  # each product is an independent topic and must not inherit another product.
  run_skill(["threads", "--json"])
  if mode != "keep":
    run_skill(["set-mode", f"--{mode}"])
  return {"active_project": active}


def main() -> int:
  load_dotenv(ROOT / ".env")
  ap = argparse.ArgumentParser(description="Batch product image/video generation through Lovart skill")
  ap.add_argument("--products-root", type=Path, default=ROOT / "產品資料")
  ap.add_argument("--prompt-file", type=Path, default=DEFAULT_PROMPT)
  ap.add_argument("--music", type=Path, default=DEFAULT_MUSIC)
  ap.add_argument("--output-root", type=Path, default=ROOT / "批次輸出")
  ap.add_argument("--project-id", help="Required only when Lovart has no active project")
  ap.add_argument("--project-name", default="產品圖與短影音批次製作")
  ap.add_argument("--mode", choices=["keep", "fast", "unlimited"], default="keep")
  ap.add_argument("--deadline-hours", type=float, default=24.0)
  ap.add_argument("--dry-run", action="store_true")
  ap.add_argument("--only", nargs="*", help="Only process these exact product folder names")
  args = ap.parse_args()

  if not args.prompt_file.exists():
    raise SystemExit(f"Prompt file not found: {args.prompt_file}")
  products = product_dirs(args.products_root)
  if args.only:
    products = [p for p in products if p.name in args.only]
  if not products:
    raise SystemExit("No product folders found.")

  args.output_root.mkdir(parents=True, exist_ok=True)
  state_path = args.output_root / "state.json"
  state = load_json(state_path, {"started_at": now(), "products": {}, "uploads": {}})
  state["started_at"] = state.get("started_at", now())
  setup(args.project_id, args.project_name, args.mode, args.dry_run)
  prompt = args.prompt_file.read_text(encoding="utf-8")

  if args.music.exists():
    music_url = upload_cached(args.music, state["uploads"], args.dry_run)
  else:
    music_url = None
    print(f"WARNING: music file not found: {args.music}")

  deadline = time.time() + args.deadline_hours * 3600
  for product in products:
    item = state["products"].setdefault(product.name, {"status": "pending"})
    if item.get("status") == "done":
      continue
    if item.get("status") == "pending_confirmation" and item.get("thread_id"):
      if args.dry_run:
        print(f"DRY-RUN pending thread retained: {product.name}")
        continue
      try:
        result = run_skill(["result", "--thread-id", item["thread_id"],
                            "--json", "--download", "--output-dir",
                            str(args.output_root / product.name)], retries=1)
        item["last_result"] = result
        final = result.get("final_status") if isinstance(result, dict) else None
        if final == "pending_confirmation" or result.get("status") == "running":
          print(f"STILL WAITING: {product.name}; thread={item['thread_id']}")
          save_json(state_path, state)
          return 2
        item["status"] = "done" if final == "done" else (final or "unknown")
        item["finished_at"] = now()
        save_json(state_path, state)
        print(f"{item['status'].upper()}: {product.name}")
        continue
      except Exception as exc:
        item.update({"status": "error", "error": str(exc), "updated_at": now()})
        save_json(state_path, state)
        print(f"ERROR retrieving pending result for {product.name}: {exc}", file=sys.stderr)
        continue
    if time.time() > deadline:
      item["status"] = "deadline_exceeded"
      save_json(state_path, state)
      print("Deadline reached; state saved. Re-run to continue.")
      break
    imgs = images_for(product)
    if not 3 <= len(imgs) <= 9:
      item.update({"status": "invalid_input", "image_count": len(imgs)})
      print(f"SKIP {product.name}: expected 3-9 images, found {len(imgs)}")
      save_json(state_path, state)
      continue
    out = args.output_root / product.name
    out.mkdir(parents=True, exist_ok=True)
    try:
      urls = [upload_cached(p, state["uploads"], args.dry_run) for p in imgs]
      if music_url:
        urls.append(music_url)
      item.update({"status": "running", "image_count": len(imgs), "started_at": now()})
      save_json(state_path, state)
      if args.dry_run:
        print(f"DRY-RUN {product.name}: {len(imgs)} images + music -> one Lovart chat")
        item.update({"status": "planned", "attachments": len(urls)})
        save_json(state_path, state)
        continue
      result = run_skill(["chat", "--prompt", prompt, "--attachments", *urls,
                          "--json", "--download", "--output-dir", str(out)], retries=1)
      item["last_result"] = result
      item["thread_id"] = result.get("thread_id") if isinstance(result, dict) else None
      final = result.get("final_status") if isinstance(result, dict) else None
      if final == "pending_confirmation":
        item["status"] = "pending_confirmation"
        print(f"PENDING CONFIRMATION: {product.name}; thread={item['thread_id']}")
        print("Review estimated cost, then run agent_skill.py confirm for this thread before resuming.")
        save_json(state_path, state)
        return 2
      item["status"] = "done" if final == "done" else (final or "unknown")
      item["finished_at"] = now()
      save_json(state_path, state)
      print(f"{item['status'].upper()}: {product.name}")
    except Exception as exc:
      item.update({"status": "error", "error": str(exc), "updated_at": now()})
      save_json(state_path, state)
      print(f"ERROR {product.name}: {exc}", file=sys.stderr)
  save_json(state_path, state)
  return 0


if __name__ == "__main__":
  try:
    raise SystemExit(main())
  except KeyboardInterrupt:
    raise SystemExit("Interrupted; state was saved after the last completed step.")
