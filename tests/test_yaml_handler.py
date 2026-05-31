"""Tests for the YAML handler."""
from __future__ import annotations

from pathlib import Path

import pytest

from context_kernel.ingester.handlers import RawEntity, RawRelationship
from context_kernel.ingester.yaml_handler import YAMLHandler


@pytest.fixture
def handler() -> YAMLHandler:
    return YAMLHandler()


def test_supports_yaml_files(handler: YAMLHandler) -> None:
    assert handler.supports(Path("ci.yaml"))
    assert handler.supports(Path("compose.yml"))
    assert handler.supports(Path("CONFIG.YAML"))
    assert not handler.supports(Path("main.py"))
    assert not handler.supports(Path("README.md"))
    assert not handler.supports(Path("data.json"))


def test_extract_empty_file(handler: YAMLHandler, tmp_path: Path) -> None:
    f = tmp_path / "empty.yaml"
    f.write_text("")
    entities, rels = handler.extract(f)
    assert entities == []
    assert rels == []


def test_extract_blank_file(handler: YAMLHandler, tmp_path: Path) -> None:
    f = tmp_path / "blank.yaml"
    f.write_text("\n\n  \n# just a comment\n")
    entities, rels = handler.extract(f)
    assert entities == []
    assert rels == []


def test_extract_malformed_file_does_not_raise(handler: YAMLHandler, tmp_path: Path) -> None:
    f = tmp_path / "broken.yaml"
    # Unbalanced/garbage YAML — must not raise.
    f.write_text("foo: [1, 2\nbar: : :\n  - oops\n")
    entities, rels = handler.extract(f)
    # Either degrades to ([], []) or, if pyyaml salvages something, no crash.
    assert isinstance(entities, list)
    assert isinstance(rels, list)


def test_gh_actions_anchor_and_jobs(handler: YAMLHandler, tmp_path: Path) -> None:
    f = tmp_path / "ci.yml"
    f.write_text(
        """
name: CI
on:
  push:
    branches: [main]
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - name: Checkout
        uses: actions/checkout@v4
      - name: Build
        run: make build
  test:
    runs-on: ubuntu-latest
    needs: build
    steps:
      - run: make test
  deploy:
    runs-on: ubuntu-latest
    needs: [build, test]
    steps:
      - run: make deploy
"""
    )
    entities, rels = handler.extract(f)
    by_name = {e.name: e for e in entities}

    # Anchor
    assert by_name["ci"].kind == "document"
    assert "LOC" in by_name["ci"].description
    assert "jobs" in by_name["ci"].description

    # Jobs
    assert by_name["job.build"].kind == "job"
    assert by_name["job.test"].kind == "job"
    assert by_name["job.deploy"].kind == "job"
    assert "ubuntu-latest" in by_name["job.build"].description
    assert "Checkout" in by_name["job.build"].description

    # Relationships from `needs:`
    edges = {(r.source_name, r.target_name) for r in rels}
    assert ("job.test", "job.build") in edges
    assert ("job.deploy", "job.build") in edges
    assert ("job.deploy", "job.test") in edges
    assert all(r.kind == "depends_on" for r in rels)


def test_compose_anchor_and_services(handler: YAMLHandler, tmp_path: Path) -> None:
    f = tmp_path / "docker-compose.yml"
    f.write_text(
        """
services:
  db:
    image: postgres:16
    ports:
      - "5432:5432"
  web:
    build:
      context: ./web
    ports:
      - "8000:8000"
    depends_on:
      - db
"""
    )
    entities, rels = handler.extract(f)
    by_name = {e.name: e for e in entities}

    assert by_name["docker-compose"].kind == "document"
    assert by_name["service.db"].kind == "service"
    assert by_name["service.web"].kind == "service"
    assert "postgres:16" in by_name["service.db"].description
    assert "5432:5432" in by_name["service.db"].description
    assert "./web" in by_name["service.web"].description

    edges = {(r.source_name, r.target_name) for r in rels}
    assert ("service.web", "service.db") in edges
    assert all(r.kind == "depends_on" for r in rels)


def test_compose_depends_on_long_form(handler: YAMLHandler, tmp_path: Path) -> None:
    f = tmp_path / "compose.yml"
    f.write_text(
        """
services:
  app:
    image: myapp
    depends_on:
      db:
        condition: service_healthy
  db:
    image: postgres
"""
    )
    _entities, rels = handler.extract(f)
    edges = {(r.source_name, r.target_name) for r in rels}
    assert ("service.app", "service.db") in edges


def test_kubernetes_manifest(handler: YAMLHandler, tmp_path: Path) -> None:
    f = tmp_path / "deploy.yaml"
    f.write_text(
        """
apiVersion: apps/v1
kind: Deployment
metadata:
  name: api
  namespace: prod
spec:
  replicas: 3
"""
    )
    entities, _rels = handler.extract(f)
    by_name = {e.name: e for e in entities}
    assert by_name["deploy"].kind == "document"
    assert by_name["Deployment.api"].kind == "deployment"
    assert "prod" in by_name["Deployment.api"].description


def test_generic_mapping_keys(handler: YAMLHandler, tmp_path: Path) -> None:
    f = tmp_path / "settings.yaml"
    f.write_text(
        """
name: my-app
version: 1.0
database:
  host: localhost
  port: 5432
features:
  - auth
  - billing
debug: true
"""
    )
    entities, rels = handler.extract(f)
    by_name = {e.name: e for e in entities}

    assert by_name["settings"].kind == "document"
    # Structures (mapping/list) get entities; scalars do not.
    assert by_name["key.database"].kind == "key"
    assert by_name["key.features"].kind == "key"
    assert "key.name" not in by_name      # scalar — skipped
    assert "key.version" not in by_name   # scalar — skipped
    assert "key.debug" not in by_name     # scalar — skipped
    assert rels == []


def test_multi_document_file(handler: YAMLHandler, tmp_path: Path) -> None:
    f = tmp_path / "manifests.yaml"
    f.write_text(
        """
apiVersion: v1
kind: Service
metadata:
  name: web
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: web
"""
    )
    entities, _rels = handler.extract(f)
    by_name = {e.name: e for e in entities}
    assert by_name["manifests"].kind == "document"
    assert "Documents: 2" in by_name["manifests"].description
    assert by_name["Service.web"].kind == "service"
    assert by_name["Deployment.web"].kind == "deployment"


def test_dangling_needs_edge_still_emitted(handler: YAMLHandler, tmp_path: Path) -> None:
    # A `needs:` reference to a job not defined here is still emitted; the
    # resolver drops dangling edges. We do NOT synthesize a node for it.
    f = tmp_path / "ci.yml"
    f.write_text(
        """
on: [push]
jobs:
  deploy:
    runs-on: ubuntu-latest
    needs: [lint]
    steps:
      - run: make deploy
"""
    )
    entities, rels = handler.extract(f)
    names = {e.name for e in entities}
    assert "job.lint" not in names  # not synthesized
    targets = {r.target_name for r in rels}
    assert "job.lint" in targets  # edge still emitted


# ── Real corpus smoke tests ─────────────────────────────────────────────

_REAL_WORKFLOW = Path(
    "test-repos/vibe-coded/sudoku/.github/workflows/deploy.yml"
)
_REAL_COMPOSE = Path(
    "test-repos/vibe-coded/locate_anything_setup/docker-compose.yml"
)


@pytest.mark.skipif(not _REAL_WORKFLOW.exists(), reason="real sudoku workflow not present")
def test_real_sudoku_workflow(handler: YAMLHandler) -> None:
    entities, rels = handler.extract(_REAL_WORKFLOW)
    by_name = {e.name: e for e in entities}
    assert by_name["deploy"].kind == "document"  # anchor
    # Real workflow defines these jobs (self-hosted runners).
    assert by_name["job.determine_environment"].kind == "job"
    assert by_name["job.terraform"].kind == "job"
    assert by_name["job.api_deploy"].kind == "job"
    # `runs-on:` is a list here; we record it on the job.
    assert "self-hosted" in by_name["job.terraform"].description
    # `needs:` dependencies resolve to other jobs in the file.
    edges = {(r.source_name, r.target_name) for r in rels}
    assert ("job.terraform", "job.determine_environment") in edges
    assert ("job.terraform", "job.detect_changes") in edges
    assert ("job.api_deploy", "job.terraform") in edges
    assert all(r.kind == "depends_on" for r in rels)


@pytest.mark.skipif(not _REAL_COMPOSE.exists(), reason="real locate compose not present")
def test_real_locate_compose(handler: YAMLHandler) -> None:
    entities, _rels = handler.extract(_REAL_COMPOSE)
    by_name = {e.name: e for e in entities}
    assert by_name["docker-compose"].kind == "document"
    # Single service, image expressed via ${VAR:-default}; raw scalar recorded.
    assert by_name["service.locate-anything"].kind == "service"
    assert "locate-anything" in by_name["service.locate-anything"].description
