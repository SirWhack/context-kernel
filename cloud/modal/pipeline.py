"""Modal function for cloud-native Context Kernel ingestion.

Triggered by the Cloudflare Worker on GitHub push webhooks.
Clones all portfolio repos, runs the full pipeline, syncs to KV + Neon.

Deploy: modal deploy cloud/modal/pipeline.py
Test:   modal run cloud/modal/pipeline.py::test_ingest
"""

import json
import os
import shutil
import subprocess
import time

import modal

app = modal.App("context-kernel-pipeline")

image = (
    modal.Image.debian_slim(python_version="3.12")
    .apt_install("git")
    .pip_install(
        "httpx>=0.27",
        "mcp>=1.0",
        "requests",
        "psycopg2-binary",
        "PyJWT",
        "cryptography",
    )
)

state_volume = modal.Volume.from_name("ck-state", create_if_missing=True)

PORTFOLIO_DIR = "/workspace"
STATE_DIR = "/state"
STATE_VOLUME_PATH = "/state/context-kernel"
REPOS = ["model-time", "evergreenlabs", "evergreenlabs-bot"]


def get_installation_token(app_id: str, private_key: str, installation_id: str) -> str:
    """Exchange GitHub App credentials for an installation token."""
    import jwt

    now = int(time.time())
    payload = {"iat": now - 60, "exp": now + 600, "iss": app_id}
    token = jwt.encode(payload, private_key, algorithm="RS256")

    import requests
    resp = requests.post(
        f"https://api.github.com/app/installations/{installation_id}/access_tokens",
        headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
    )
    resp.raise_for_status()
    return resp.json()["token"]


def clone_repos(github_token: str, owner: str):
    """Clone all portfolio repos into PORTFOLIO_DIR."""
    os.makedirs(PORTFOLIO_DIR, exist_ok=True)
    for repo in REPOS:
        dest = os.path.join(PORTFOLIO_DIR, repo)
        if os.path.exists(dest):
            shutil.rmtree(dest)
        url = f"https://x-access-token:{github_token}@github.com/{owner}/{repo}.git"
        subprocess.run(
            ["git", "clone", "--depth", "1", url, dest],
            check=True, capture_output=True,
        )
        print(f"Cloned {owner}/{repo}")


def restore_state():
    """Copy persisted state from Modal volume to workspace."""
    ck_dir = os.path.join(PORTFOLIO_DIR, ".context-kernel")
    if os.path.exists(STATE_VOLUME_PATH):
        if os.path.exists(ck_dir):
            shutil.rmtree(ck_dir)
        shutil.copytree(STATE_VOLUME_PATH, ck_dir)
        print(f"Restored state from volume ({count_files(ck_dir)} files)")
    else:
        os.makedirs(ck_dir, exist_ok=True)
        print("No existing state — starting fresh")


def save_state():
    """Copy workspace state back to Modal volume for persistence."""
    ck_dir = os.path.join(PORTFOLIO_DIR, ".context-kernel")
    if os.path.exists(STATE_VOLUME_PATH):
        shutil.rmtree(STATE_VOLUME_PATH)
    shutil.copytree(
        ck_dir, STATE_VOLUME_PATH,
        ignore=shutil.ignore_patterns("embeddings", "summaries", "views"),
    )
    state_volume.commit()
    print(f"Saved state to volume ({count_files(STATE_VOLUME_PATH)} files)")


def count_files(path):
    return sum(len(files) for _, _, files in os.walk(path))


def write_config(portfolio_root: str):
    """Write a config.toml for the pipeline, using env vars for endpoints."""
    config = f"""\
portfolio_root = "{portfolio_root}"

[[projects]]
path = "model-time"

[[projects]]
path = "evergreenlabs"

[[projects]]
path = "evergreenlabs-bot"

[ingester]
summarizer_model = "deepseek-v4-flash"
summarizer_endpoint = "https://api.deepseek.com/v1"
embedder_model = "@cf/qwen/qwen3-embedding-0.6b"
embedder_endpoint = "https://api.cloudflare.com/client/v4/accounts/{os.environ['CF_ACCOUNT_ID']}/ai/v1"
parallel_requests = 50

[[materializer.views]]
name = "index"
kind = "index"
"""
    config_path = os.path.join(portfolio_root, ".context-kernel", "config.toml")
    with open(config_path, "w") as f:
        f.write(config)
    print(f"Wrote config to {config_path}")


def run_pipeline():
    """Run ck ingest + ck materialize + sync."""
    import sys
    sys.path.insert(0, os.path.join(PORTFOLIO_DIR, "model-time"))

    env = {
        **os.environ,
        "PYTHONPATH": os.path.join(PORTFOLIO_DIR, "model-time"),
        "DEEPSEEK_API_KEY": os.environ["DEEPSEEK_API_KEY"],
        "CF_USER": os.environ["CF_ACCOUNT_ID"],
        "CF_WORKER_AI_TOKEN": os.environ["CF_WORKER_AI_TOKEN"],
    }
    config_path = os.path.join(PORTFOLIO_DIR, ".context-kernel", "config.toml")

    print("\n=== Ingest ===")
    subprocess.run(
        [
            "python", "-m", "context_kernel.agent_cli",
            "ingest", "--portfolio", PORTFOLIO_DIR,
        ],
        env=env, check=True, cwd=os.path.join(PORTFOLIO_DIR, "model-time"),
    )

    print("\n=== Materialize ===")
    subprocess.run(
        [
            "python", "-m", "context_kernel.agent_cli",
            "materialize", "--all", "--config", config_path,
        ],
        env=env, check=True, cwd=os.path.join(PORTFOLIO_DIR, "model-time"),
    )

    print("\n=== Sync KV + Neon ===")
    sync_env = {
        **env,
        "CF_API_TOKEN": os.environ["WORKER_TOKEN"],
        "KV_NAMESPACE_ID": os.environ["KV_NAMESPACE_ID"],
        "DATABASE_URL": os.environ["DATABASE_URL"],
    }
    subprocess.run(
        [
            "python",
            os.path.join(PORTFOLIO_DIR, "model-time", "cloud", "mcp-server", "sync.py"),
            "--portfolio", PORTFOLIO_DIR,
        ],
        env=sync_env, check=True,
    )


@app.function(
    image=image,
    volumes={STATE_DIR: state_volume},
    secrets=[modal.Secret.from_name("context-kernel")],
    timeout=900,
    cpu=2,
    memory=2048,
)
@modal.web_endpoint(method="POST")
def ingest(body: dict):
    """Webhook endpoint called by the Cloudflare Worker on GitHub push."""
    trigger_token = os.environ.get("TRIGGER_TOKEN", "")
    if body.get("token") != trigger_token:
        return {"error": "unauthorized"}, 401

    owner = os.environ["GITHUB_OWNER"]
    start = time.time()

    print(f"Processing push to {body.get('repo', 'unknown')}")

    github_token = get_installation_token(
        os.environ["GITHUB_APP_ID"],
        os.environ["GITHUB_APP_PRIVATE_KEY"],
        os.environ["GITHUB_APP_INSTALLATION_ID"],
    )

    clone_repos(github_token, owner)
    restore_state()
    write_config(PORTFOLIO_DIR)
    run_pipeline()
    save_state()

    elapsed = time.time() - start
    print(f"\nPipeline complete in {elapsed:.1f}s")
    return {"ok": True, "elapsed": round(elapsed, 1)}


@app.local_entrypoint()
def test_ingest():
    """Test the pipeline locally: modal run cloud/modal/pipeline.py::test_ingest"""
    result = ingest.remote({"token": os.environ.get("TRIGGER_TOKEN", "test"), "repo": "manual-test"})
    print(f"Result: {result}")
