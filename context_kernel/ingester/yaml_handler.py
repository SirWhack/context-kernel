"""YAML source handler (StructuredHandler).

YAML has a grammar, so we parse it with pyyaml rather than chunking it into the
Summarizer. Each file yields one anchor `document` entity (named after the file)
plus child entities for the meaningful top-level structures we recognise:

  - GitHub Actions workflows (top-level ``on``/``jobs``)  → ``job.<id>`` entities
  - docker-compose files (top-level ``services``)          → ``service.<name>``
  - Kubernetes manifests (``apiVersion``+``kind``+name)    → ``<kind>.<name>``
  - anything else                                          → ``key.<name>``

Relationships are emitted only when they are name-resolvable inside the file
(GH-Actions ``needs:`` and compose ``depends_on:``). We never synthesize a node
for a dangling reference — the resolver drops edges to entities not in the graph.

The handler never raises: malformed YAML, blank files, and surprising shapes all
degrade to ``([], [])`` or a bare anchor, matching the contract that ingestion is
crash-safe (see the Terraform/Bicep handlers for the same posture).
"""

from __future__ import annotations

import logging
from pathlib import Path

import yaml

from context_kernel.ingester.handlers import RawEntity, RawRelationship

log = logging.getLogger(__name__)

_YAML_EXTENSIONS = {".yaml", ".yml"}


def _as_str(value: object) -> str:
    """Render a scalar YAML value compactly for a description line."""
    if isinstance(value, str):
        return value
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _summarize_value(value: object) -> str:
    """One-line shape hint for a top-level value (mapping/list/scalar)."""
    if isinstance(value, dict):
        keys = list(value.keys())
        shown = ", ".join(_as_str(k) for k in keys[:6])
        more = f", +{len(keys) - 6} more" if len(keys) > 6 else ""
        return f"mapping({len(keys)} keys: {shown}{more})" if keys else "mapping(empty)"
    if isinstance(value, list):
        return f"list({len(value)} items)"
    return f"scalar({_as_str(value)!r})"


def _step_label(step: object) -> str:
    """Best-effort label for a GitHub Actions step."""
    if not isinstance(step, dict):
        return _as_str(step)
    if step.get("name"):
        return _as_str(step["name"])
    if step.get("uses"):
        return f"uses {_as_str(step['uses'])}"
    if step.get("run"):
        run = _as_str(step["run"]).strip().splitlines()
        return f"run {run[0]}" if run else "run"
    return "(step)"


def _is_gh_actions(doc: dict) -> bool:
    # `on` round-trips to the Python bool True under YAML 1.1 (the "Norway
    # problem" sibling), so accept either the string key or that bool.
    has_on = "on" in doc or True in doc
    return has_on and isinstance(doc.get("jobs"), dict)


def _is_compose(doc: dict) -> bool:
    return isinstance(doc.get("services"), dict)


def _is_k8s(doc: dict) -> bool:
    meta = doc.get("metadata")
    return (
        "apiVersion" in doc
        and "kind" in doc
        and isinstance(meta, dict)
        and bool(meta.get("name"))
    )


def _dep_list(value: object) -> list[str]:
    """Normalise a `needs:`/`depends_on:` value to a list of names.

    Accepts a scalar, a list, or (compose long-form) a mapping of name → opts.
    """
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [_as_str(v) for v in value]
    if isinstance(value, dict):
        return [_as_str(k) for k in value.keys()]
    return []


class YAMLHandler:
    """Extract document/key/job/service entities from YAML via pyyaml."""

    def supports(self, path: Path) -> bool:
        return path.suffix.lower() in _YAML_EXTENSIONS

    def extract(self, path: Path) -> tuple[list[RawEntity], list[RawRelationship]]:
        text = path.read_text(encoding="utf-8", errors="replace")
        anchor_name = path.stem
        total_loc = text.count("\n") + 1 if text else 0

        if not text.strip():
            return [], []

        try:
            docs = [d for d in yaml.safe_load_all(text) if d is not None]
        except yaml.YAMLError as exc:
            log.warning("YAML parse error in %s, skipping: %s", path, exc)
            return [], []
        except Exception as exc:  # noqa: BLE001 — ingestion must never crash
            log.warning("Unexpected error reading %s, skipping: %s", path, exc)
            return [], []

        if not docs:
            return [], []

        entities: list[RawEntity] = []
        relationships: list[RawRelationship] = []

        # ── Gather top-level keys across all documents for the anchor ────
        top_keys: list[str] = []
        for doc in docs:
            if isinstance(doc, dict):
                top_keys.extend(_as_str(k) for k in doc.keys())
        keys_section = ", ".join(top_keys) if top_keys else "(none — non-mapping root)"
        doc_note = f"\n  Documents: {len(docs)}" if len(docs) > 1 else ""

        anchor_desc = (
            f"Document: {path}\n"
            f"  Keys:\n"
            f"    {keys_section}\n"
            f"  Depth: {len(top_keys)} top-level keys, {total_loc} LOC{doc_note}"
        )
        entities.append(RawEntity(name=anchor_name, kind="document", description=anchor_desc))

        # ── Per-document child extraction ───────────────────────────────
        for doc in docs:
            if not isinstance(doc, dict):
                continue
            if _is_k8s(doc):
                self._extract_k8s(doc, str(path), entities)
            elif _is_gh_actions(doc):
                self._extract_gh_actions(doc, str(path), entities, relationships)
            elif _is_compose(doc):
                self._extract_compose(doc, str(path), entities, relationships)
            else:
                self._extract_generic(doc, str(path), entities)

        return entities, relationships

    # ── GitHub Actions ──────────────────────────────────────────────────

    def _extract_gh_actions(
        self,
        doc: dict,
        rel_path: str,
        entities: list[RawEntity],
        relationships: list[RawRelationship],
    ) -> None:
        jobs = doc.get("jobs")
        if not isinstance(jobs, dict):
            return
        job_names = {f"job.{_as_str(jid)}" for jid in jobs.keys()}
        for jid, job in jobs.items():
            name = f"job.{_as_str(jid)}"
            job = job if isinstance(job, dict) else {}
            runs_on = job.get("runs-on")
            steps = job.get("steps") if isinstance(job.get("steps"), list) else []
            step_labels = [_step_label(s) for s in steps]
            steps_str = "\n    ".join(step_labels) if step_labels else "(none)"

            desc = (
                f"Job: {jid}\n"
                f"  File: {rel_path}\n"
                f"  Runs-on: {_as_str(runs_on) if runs_on is not None else '—'}\n"
                f"  Steps:\n"
                f"    {steps_str}\n"
                f"  Depth: {len(step_labels)} steps"
            )
            entities.append(RawEntity(name=name, kind="job", description=desc))

            for dep in _dep_list(job.get("needs")):
                target = f"job.{dep}"
                relationships.append(RawRelationship(
                    source_name=name,
                    target_name=target,
                    kind="depends_on",
                    description=f"{name} needs {target}",
                ))
                # job_names retained for reference; resolver drops dangling edges.
        _ = job_names

    # ── docker-compose ──────────────────────────────────────────────────

    def _extract_compose(
        self,
        doc: dict,
        rel_path: str,
        entities: list[RawEntity],
        relationships: list[RawRelationship],
    ) -> None:
        services = doc.get("services")
        if not isinstance(services, dict):
            return
        for sname, svc in services.items():
            name = f"service.{_as_str(sname)}"
            svc = svc if isinstance(svc, dict) else {}
            image = svc.get("image")
            build = svc.get("build")
            ports = svc.get("ports") if isinstance(svc.get("ports"), list) else []
            depends = _dep_list(svc.get("depends_on"))

            if isinstance(build, dict):
                build_str = _as_str(build.get("context", "(build)"))
            elif build is not None:
                build_str = _as_str(build)
            else:
                build_str = "—"

            desc = (
                f"Service: {sname}\n"
                f"  File: {rel_path}\n"
                f"  Image: {_as_str(image) if image is not None else '—'}\n"
                f"  Build: {build_str}\n"
                f"  Ports: {', '.join(_as_str(p) for p in ports) if ports else '—'}\n"
                f"  Depends-on: {', '.join(depends) if depends else '—'}"
            )
            entities.append(RawEntity(name=name, kind="service", description=desc))

            for dep in depends:
                relationships.append(RawRelationship(
                    source_name=name,
                    target_name=f"service.{dep}",
                    kind="depends_on",
                    description=f"{name} depends on service.{dep}",
                ))

    # ── Kubernetes ──────────────────────────────────────────────────────

    def _extract_k8s(self, doc: dict, rel_path: str, entities: list[RawEntity]) -> None:
        kind = _as_str(doc.get("kind"))
        meta = doc.get("metadata") or {}
        res_name = _as_str(meta.get("name"))
        name = f"{kind}.{res_name}"
        namespace = meta.get("namespace")
        api_version = _as_str(doc.get("apiVersion"))

        desc = (
            f"{kind}: {res_name}\n"
            f"  File: {rel_path}\n"
            f"  apiVersion: {api_version}\n"
            f"  Namespace: {_as_str(namespace) if namespace is not None else 'default'}"
        )
        entities.append(RawEntity(name=name, kind=kind.lower(), description=desc))

    # ── Generic fallback ────────────────────────────────────────────────

    def _extract_generic(self, doc: dict, rel_path: str, entities: list[RawEntity]) -> None:
        for key, value in doc.items():
            # Skip scalar top-level keys to avoid noise; only structures get nodes.
            if not isinstance(value, (dict, list)):
                continue
            name = f"key.{_as_str(key)}"
            desc = (
                f"Key: {_as_str(key)}\n"
                f"  File: {rel_path}\n"
                f"  Value: {_summarize_value(value)}"
            )
            entities.append(RawEntity(name=name, kind="key", description=desc))
