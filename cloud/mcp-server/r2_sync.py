#!/usr/bin/env python3
"""Upload/download .context-kernel/ state to/from Cloudflare R2 as a tar.gz archive.

The pipeline state (~16 MB uncompressed, ~5 MB compressed) is stored as a single
R2 object to minimize API round-trips. Only cache/, graph/, and config.toml are
included — derived artifacts (embeddings/, summaries/, views/) are regenerable.

Env vars:
  CF_API_TOKEN   — Cloudflare API token (R2 read/write)
  CF_ACCOUNT_ID  — Cloudflare account ID

Usage:
  python r2_sync.py upload  --bucket context-kernel-state --local-dir /path/to/.context-kernel
  python r2_sync.py download --bucket context-kernel-state --local-dir /path/to/.context-kernel
  python r2_sync.py download --bucket context-kernel-state --local-dir /path/to/.context-kernel --portfolio-root /new/root
"""

import argparse
import io
import os
import re
import sys
import tarfile
import tempfile

import requests

R2_OBJECT_KEY = "state.tar.gz"

INCLUDE_DIRS = {"cache", "graph"}
INCLUDE_FILES = {"config.toml", "log.md"}


def r2_url(account_id: str, bucket: str, key: str) -> str:
    return f"https://api.cloudflare.com/client/v4/accounts/{account_id}/r2/buckets/{bucket}/objects/{key}"


def upload(local_dir: str, account_id: str, bucket: str, token: str) -> None:
    local = os.path.abspath(local_dir)
    if not os.path.isdir(local):
        sys.exit(f"Directory not found: {local}")

    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for entry in sorted(os.listdir(local)):
            full = os.path.join(local, entry)
            if entry in INCLUDE_DIRS and os.path.isdir(full):
                tar.add(full, arcname=entry)
                count = sum(len(files) for _, _, files in os.walk(full))
                print(f"  Added {entry}/ ({count} files)")
            elif entry in INCLUDE_FILES and os.path.isfile(full):
                tar.add(full, arcname=entry)
                print(f"  Added {entry}")

    data = buf.getvalue()
    print(f"\nArchive size: {len(data) / 1024 / 1024:.1f} MB")

    url = r2_url(account_id, bucket, R2_OBJECT_KEY)
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/gzip"}
    resp = requests.put(url, headers=headers, data=data)
    resp.raise_for_status()
    print(f"Uploaded to r2://{bucket}/{R2_OBJECT_KEY}")


def download(local_dir: str, account_id: str, bucket: str, token: str, portfolio_root: str | None = None) -> None:
    url = r2_url(account_id, bucket, R2_OBJECT_KEY)
    headers = {"Authorization": f"Bearer {token}"}
    resp = requests.get(url, headers=headers)

    if resp.status_code == 404:
        print("No existing state in R2 — starting fresh")
        os.makedirs(local_dir, exist_ok=True)
        return

    resp.raise_for_status()
    data = resp.content
    print(f"Downloaded {len(data) / 1024 / 1024:.1f} MB from r2://{bucket}/{R2_OBJECT_KEY}")

    os.makedirs(local_dir, exist_ok=True)
    buf = io.BytesIO(data)
    with tarfile.open(fileobj=buf, mode="r:gz") as tar:
        tar.extractall(path=local_dir, filter="data")

    entries = os.listdir(local_dir)
    print(f"Extracted to {local_dir}: {', '.join(sorted(entries))}")

    if portfolio_root:
        config_path = os.path.join(local_dir, "config.toml")
        if os.path.exists(config_path):
            with open(config_path) as f:
                config = f.read()
            config = re.sub(
                r'portfolio_root\s*=\s*"[^"]*"',
                f'portfolio_root = "{portfolio_root}"',
                config,
            )
            with open(config_path, "w") as f:
                f.write(config)
            print(f"Patched config.toml portfolio_root → {portfolio_root}")


def main():
    parser = argparse.ArgumentParser(description="Sync .context-kernel/ state to/from R2")
    parser.add_argument("action", choices=["upload", "download"])
    parser.add_argument("--bucket", default="context-kernel-state")
    parser.add_argument("--local-dir", required=True)
    parser.add_argument("--portfolio-root", help="Patch config.toml portfolio_root on download")
    args = parser.parse_args()

    account_id = os.environ.get("CF_ACCOUNT_ID") or os.environ.get("CF_USER")
    token = os.environ.get("CF_API_TOKEN")
    if not account_id:
        sys.exit("Set CF_ACCOUNT_ID env var")
    if not token:
        sys.exit("Set CF_API_TOKEN env var")

    if args.action == "upload":
        print(f"Uploading {args.local_dir} → r2://{args.bucket}/")
        upload(args.local_dir, account_id, args.bucket, token)
    else:
        print(f"Downloading r2://{args.bucket}/ → {args.local_dir}")
        download(args.local_dir, account_id, args.bucket, token, args.portfolio_root)


if __name__ == "__main__":
    main()
