#!/usr/bin/env python3
"""One-time migration: move all existing emotion/contextual animations to inbox.

Usage:
    python scripts/migrate_to_inbox.py [--dry-run]
"""
import argparse
import shutil
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
ANIMATIONS = PROJECT_ROOT / "data" / "animations"
INBOX = ANIMATIONS / "inbox"
OLD_DIRS = [ANIMATIONS / "emotions", ANIMATIONS / "contextual", ANIMATIONS / "states"]

def migrate(dry_run: bool = False) -> None:
    INBOX.mkdir(parents=True, exist_ok=True)
    moved, skipped = 0, 0
    for old_dir in OLD_DIRS:
        if not old_dir.exists():
            continue
        for f in old_dir.rglob("*"):
            if not f.is_file():
                continue
            if f.suffix.lower() not in {".webp", ".gif", ".png", ".jpg"}:
                continue
            dest = INBOX / f.name
            # Avoid clobbering — append suffix if name collision
            if dest.exists():
                dest = INBOX / f"{f.stem}_{f.parent.name}{f.suffix}"
            print(f"{'[DRY]' if dry_run else 'MOVE'} {f.relative_to(PROJECT_ROOT)} → {dest.relative_to(PROJECT_ROOT)}")
            if not dry_run:
                shutil.move(str(f), str(dest))
            moved += 1
    if not dry_run:
        # Remove now-empty old dirs
        for old_dir in OLD_DIRS:
            if old_dir.exists():
                try:
                    shutil.rmtree(old_dir)
                    print(f"REMOVED {old_dir.relative_to(PROJECT_ROOT)}/")
                except OSError as e:
                    print(f"WARN could not remove {old_dir}: {e}")
    print(f"\n{'[DRY RUN] Would move' if dry_run else 'Moved'} {moved} files, skipped {skipped}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    migrate(dry_run=args.dry_run)
