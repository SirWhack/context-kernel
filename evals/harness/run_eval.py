#!/usr/bin/env python3
"""Kernel-vs-grep A/B eval runner (battery mode).

For one repo, runs TWO headless Claude Code (sonnet) sessions — a kernel arm and a grep
arm — each answering the same numbered battery of curated questions, captures the
stream-json transcript of each, emits the matching gold.toml, and (by default) scores the
pair with scripts/h2_eval.py.

  Arm A (kernel): ONLY the per-repo Context Kernel MCP (`find` / `overview`) + `Read`.
                  Discovers via the kernel, confirms by reading the exact paths it cites.
                  No grep, glob, or shell.
  Arm B (grep):   ONLY `Grep` / `Glob` / `Read` / `Bash` over the raw tree. No kernel, no MCP.

Why headless `claude` and not the Agent tool: the kernel arm must talk to *this repo's*
local graph. The connected `context-kernel` MCP is the cloud worker (one Neon graph), and
Agent-tool sub-agents inherit it — wrong graph. So each kernel-arm session gets its own
stdio `ck mcp --config <repo>/.context-kernel/config.toml` via `--strict-mcp-config`.

The battery shape (one session, `## Q1`…`## Qn`, each ending in a `Files:` list) is what
h2_eval scores natively: COST + HALLUCINATION per session, RECALL per question vs gold,
ASPECT-PRECISION if the repo has an ontology (foreign repos don't — that axis is skipped).

The first user turn carries the arm's signal words ("Context Kernel" -> kernel,
"grep"/"baseline" -> grep); we also prepend a synthetic user line so arm detection is
robust to whatever stream-json echoes.

Usage:
  python evals/harness/run_eval.py --repo full-stack-fastapi-template            # both arms + score
  python evals/harness/run_eval.py --repo full-stack-fastapi-template --arm kernel --no-score
  python evals/harness/run_eval.py --repo full-stack-fastapi-template --score-only

Outputs  evals/runs/sessions/<repo>/battery-<arm>.jsonl   (gitignored — corpus content)
         evals/runs/sessions/<repo>/battery-<arm>.err      (stderr, for debugging)
         evals/runs/sessions/<repo>/gold.toml              (recall oracle from the task file)
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CK = ROOT / ".venv" / "bin" / "ck"
SESSIONS = ROOT / "evals" / "runs" / "sessions"

# Escape hatches blocked for BOTH arms — without these the grep arm reached for `Workflow`
# and orchestrated 5 hidden sub-agents (pilot run), making it not a grep baseline at all.
# --disallowedTools binds even under bypassPermissions (verified); --allowedTools does not.
ESCAPE = [
    "Workflow", "Agent", "Task", "TaskCreate", "TaskUpdate", "TaskGet", "TaskList",
    "TaskOutput", "TaskStop", "TeamCreate", "TeamDelete", "SendMessage", "Monitor",
    "CronCreate", "CronDelete", "CronList", "RemoteTrigger", "PushNotification",
    "NotebookEdit", "EnterPlanMode", "ExitPlanMode", "EnterWorktree", "ExitWorktree",
    "Skill", "ScheduleWakeup", "Edit", "Write", "MultiEdit", "WebFetch", "WebSearch",
    "ListMcpResourcesTool", "ReadMcpResourceTool",
]
ARMS = {
    # kernel keeps ToolSearch (the sub-session loads mcp__ck__* as deferred tools); the
    # escape list still blocks it from CALLING anything beyond find/overview/Read.
    "kernel": {
        "allowed": ["mcp__ck__find", "mcp__ck__overview", "Read", "ToolSearch"],
        "denied": ESCAPE + ["Grep", "Glob", "Bash"],
    },
    "grep": {
        "allowed": ["Grep", "Glob", "Read", "Bash"],
        "denied": ESCAPE + ["ToolSearch", "mcp__ck__find", "mcp__ck__overview"],
    },
}

PREAMBLE = {
    "kernel": (
        "Arm A. "
        "You are orienting in an unfamiliar codebase using ONLY the Context Kernel MCP "
        "tools — `find` (semantic search over the repo's knowledge graph) and `overview` "
        "(a scope/directory's orientation summary) — plus `Read`. You may NOT grep, glob, "
        "or browse the filesystem: locate everything through the Context Kernel, then `Read` "
        "the exact files it cites to confirm."
    ),
    "grep": (
        "Arm B. "
        "You are orienting in an unfamiliar codebase to establish a baseline, using ONLY "
        "grep/ripgrep, glob, and file reads over the raw repository — no Context Kernel, no "
        "MCP tools. Any `AGENTS.md` or `CLAUDE.md` files in the tree are generated artifacts, "
        "not part of the project — ignore them and work from the real source."
    ),
}

FORMAT = (
    "\n\nTarget repository (all file paths relative to here): {repo}\n\n"
    "Answer the {n} questions below. For EACH question, write a markdown header `## Q{{i}}` "
    "with its number, give a concise answer, and end that question with a line `Files:` "
    "followed by every source file path that answers it — one per line, in backticks, "
    "relative to the repo root.\n\n"
    "CRITICAL: list a file ONLY if you actually OPENED it this session (read its contents "
    "via your allowed tools). Do NOT list files from prior knowledge or memory of this or "
    "any public project — if you did not open it in this session, do not cite it.\n\n"
    "{questions}"
)


def load_env(env_path: Path) -> dict:
    out = {}
    if not env_path.exists():
        return out
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def load_tasks(repo: str) -> dict:
    f = ROOT / "evals" / "harness" / "tasks" / f"{repo}.json"
    if not f.exists():
        sys.exit(f"no task file: {f}")
    return json.loads(f.read_text())


def build_prompt(arm: str, repo_abs: Path, tasks: list) -> str:
    qs = "\n\n".join(f"## Q{i + 1}\n{t['question']}" for i, t in enumerate(tasks))
    return PREAMBLE[arm] + FORMAT.format(repo=repo_abs, n=len(tasks), questions=qs)


def write_gold(repo: str, tasks: list) -> Path:
    out = SESSIONS / repo / "gold.toml"
    out.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    for i, t in enumerate(tasks):
        files = ", ".join(json.dumps(g) for g in t["gold"])
        lines.append(f"[Q{i + 1}]\nfiles = [{files}]\n")
    out.write_text("\n".join(lines))
    return out


def run_arm(repo: str, arm: str, tasks: list, base_env: dict, timeout: int) -> Path:
    repo_abs = ROOT / "test-repos" / repo
    cfg = repo_abs / ".context-kernel" / "config.toml"
    if not cfg.exists():
        sys.exit(f"repo not ingested (no config): {cfg}")

    prompt = build_prompt(arm, repo_abs, tasks)
    out_dir = SESSIONS / repo
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / f"battery-{arm}.jsonl"
    err_file = out_dir / f"battery-{arm}.err"

    cmd = [
        "claude", "-p", prompt,
        "--model", "sonnet",
        "--output-format", "stream-json", "--verbose",
        "--permission-mode", "bypassPermissions",
        "--add-dir", str(repo_abs),
        "--strict-mcp-config",
    ]
    mcp_cfg_path = None
    if arm == "kernel":
        mcp_obj = {"mcpServers": {"ck": {"command": str(CK),
                   "args": ["mcp", "--config", str(cfg)]}}}
        fd, mcp_cfg_path = tempfile.mkstemp(suffix=".mcp.json", prefix="ck-eval-")
        Path(mcp_cfg_path).write_text(json.dumps(mcp_obj))
        os.close(fd)
        cmd += ["--mcp-config", mcp_cfg_path]
    cmd += ["--allowedTools", *ARMS[arm]["allowed"]]
    cmd += ["--disallowedTools", *ARMS[arm]["denied"]]

    work = tempfile.mkdtemp(prefix="ck-eval-cwd-")  # neutral cwd: no CLAUDE.md auto-load
    env = {**os.environ, **base_env}

    print(f"  [{arm:6}] running {len(tasks)} questions … ", end="", flush=True)
    with open(err_file, "w") as ef:
        proc = subprocess.run(cmd, cwd=work, env=env, stdout=subprocess.PIPE,
                              stderr=ef, text=True, timeout=timeout)
    user_line = json.dumps({"type": "user", "message": {"role": "user",
              "content": [{"type": "text", "text": prompt}]}})
    out_file.write_text(user_line + "\n" + proc.stdout)
    if mcp_cfg_path:
        os.unlink(mcp_cfg_path)
    print(f"rc={proc.returncode} lines={proc.stdout.count(chr(10))} -> {out_file.relative_to(ROOT)}")
    return out_file


def score(repo: str, base_env: dict) -> None:
    out_dir = SESSIONS / repo
    k, g = out_dir / "battery-kernel.jsonl", out_dir / "battery-grep.jsonl"
    gold = out_dir / "gold.toml"
    if not (k.exists() and g.exists()):
        sys.exit("both arms must be run before scoring")
    cmd = [str(ROOT / ".venv/bin/python"), str(ROOT / "scripts/h2_eval.py"),
           str(k), str(g), "--gold", str(gold)]
    env = {**os.environ, "CK_PORTFOLIO": f"test-repos/{repo}"}
    print("\n" + "=" * 70)
    subprocess.run(cmd, cwd=ROOT, env=env)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--arm", choices=["kernel", "grep"], help="run one arm only")
    ap.add_argument("--no-score", action="store_true")
    ap.add_argument("--score-only", action="store_true")
    ap.add_argument("--timeout", type=int, default=600)
    args = ap.parse_args()

    data = load_tasks(args.repo)
    tasks = data["tasks"]
    base_env = load_env(ROOT / ".env")
    write_gold(args.repo, tasks)

    if not args.score_only:
        arms = [args.arm] if args.arm else ["kernel", "grep"]
        for arm in arms:
            run_arm(args.repo, arm, tasks, base_env, args.timeout)

    if not args.no_score and not args.arm:
        score(args.repo, base_env)
    return 0


if __name__ == "__main__":
    sys.exit(main())
