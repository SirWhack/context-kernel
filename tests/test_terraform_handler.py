"""Tests for the Terraform (HCL) handler."""
from __future__ import annotations

from pathlib import Path

import pytest

from context_kernel.ingester.handlers import RawEntity, RawRelationship
from context_kernel.ingester.terraform_handler import TerraformHandler


@pytest.fixture
def handler() -> TerraformHandler:
    return TerraformHandler()


def test_supports_terraform_files(handler: TerraformHandler) -> None:
    assert handler.supports(Path("main.tf"))
    assert handler.supports(Path("MAIN.TF"))
    assert not handler.supports(Path("main.py"))
    assert not handler.supports(Path("README.md"))
    assert not handler.supports(Path("vars.tfvars"))


def test_extract_empty_file(handler: TerraformHandler, tmp_path: Path) -> None:
    f = tmp_path / "empty.tf"
    f.write_text("")
    entities, rels = handler.extract(f)
    # module anchor always present
    assert len(entities) == 1
    assert entities[0].kind == "module"
    assert entities[0].name == "empty"
    assert "0 resources" in entities[0].description
    assert rels == []


def test_extract_malformed_file(handler: TerraformHandler, tmp_path: Path) -> None:
    f = tmp_path / "broken.tf"
    # Unbalanced braces / garbage — must not raise.
    f.write_text('resource "aws_s3_bucket" "x" {\n  bucket = "y"\n')
    entities, rels = handler.extract(f)
    # Should still emit the anchor at minimum, no exception.
    assert any(e.kind == "module" and e.name == "broken" for e in entities)


def test_anchor_and_block_entities(handler: TerraformHandler, tmp_path: Path) -> None:
    f = tmp_path / "main.tf"
    f.write_text(
        """
provider "aws" {
  region = var.region
}

variable "region" {
  default = "us-east-1"
}

output "bucket_arn" {
  value = aws_s3_bucket.assets.arn
}

data "aws_ami" "ubuntu" {
  most_recent = true
}

module "vpc" {
  source = "./modules/vpc"
}

resource "aws_s3_bucket" "assets" {
  bucket = "my-assets"
}

resource "aws_cloudfront_distribution" "cdn" {
  origin {
    domain_name = aws_s3_bucket.assets.bucket_regional_domain_name
  }
}
"""
    )
    entities, rels = handler.extract(f)
    by_name = {e.name: e for e in entities}

    # Anchor
    assert by_name["main"].kind == "module"
    assert "LOC" in by_name["main"].description

    # Reference-syntax names + kinds
    assert by_name["var.region"].kind == "variable"
    assert by_name["output.bucket_arn"].kind == "output"
    assert by_name["data.aws_ami.ubuntu"].kind == "data"
    assert by_name["module.vpc"].kind == "module_call"
    assert by_name["provider.aws"].kind == "provider"
    assert by_name["aws_s3_bucket.assets"].kind == "resource"
    assert by_name["aws_cloudfront_distribution.cdn"].kind == "resource"


def test_cross_resource_reference(handler: TerraformHandler, tmp_path: Path) -> None:
    f = tmp_path / "main.tf"
    f.write_text(
        """
variable "region" {
  default = "us-east-1"
}

resource "aws_s3_bucket" "assets" {
  bucket = "my-assets"
}

resource "aws_cloudfront_distribution" "cdn" {
  origin {
    domain_name = aws_s3_bucket.assets.bucket_regional_domain_name
  }
}
"""
    )
    _entities, rels = handler.extract(f)
    edges = {(r.source_name, r.target_name) for r in rels}
    # cdn references the bucket; trailing attribute access stripped.
    assert ("aws_cloudfront_distribution.cdn", "aws_s3_bucket.assets") in edges
    # `references` edges still present alongside the new `contains` edges (Fix A).
    assert any(r.kind == "references" for r in rels)


def test_anchor_contains_declared_blocks(handler: TerraformHandler, tmp_path: Path) -> None:
    """Fix A: the file `module` anchor emits a `contains` edge to each block."""
    f = tmp_path / "s3.tf"
    f.write_text(
        """
resource "aws_s3_bucket" "assets" {
  bucket = "my-assets"
}

variable "region" {
  default = "us-east-1"
}
"""
    )
    _entities, rels = handler.extract(f)
    contains = {
        (r.source_name, r.target_name) for r in rels if r.kind == "contains"
    }
    assert ("s3", "aws_s3_bucket.assets") in contains
    assert ("s3", "var.region") in contains
    # The anchor never contains itself.
    assert ("s3", "s3") not in contains


def test_anchor_does_not_contain_itself(handler: TerraformHandler, tmp_path: Path) -> None:
    # No false self-containment edge even when nothing else is declared.
    f = tmp_path / "empty.tf"
    f.write_text("")
    _entities, rels = handler.extract(f)
    assert not any(r.kind == "contains" for r in rels)


def test_resource_description_has_infra_framing(
    handler: TerraformHandler, tmp_path: Path
) -> None:
    """Fix B: resource descriptions carry infra/deploy vocabulary + the type."""
    f = tmp_path / "lambda.tf"
    f.write_text(
        """
resource "aws_lambda_function" "api" {
  function_name = "api"
}
"""
    )
    entities, _rels = handler.extract(f)
    by_name = {e.name: e for e in entities}
    desc = by_name["aws_lambda_function.api"].description
    assert "infrastructure/deployment" in desc.lower()
    assert "aws_lambda_function" in desc


def test_anchor_description_has_infra_framing(
    handler: TerraformHandler, tmp_path: Path
) -> None:
    """Fix B: the module anchor frames the file as infra/deploy config."""
    f = tmp_path / "s3.tf"
    f.write_text(
        """
resource "aws_s3_bucket" "assets" {
  bucket = "my-assets"
}
"""
    )
    entities, _rels = handler.extract(f)
    anchor = next(e for e in entities if e.kind == "module" and e.name == "s3")
    assert "infrastructure/deployment" in anchor.description.lower()
    # Anchor still lists declared resources.
    assert "aws_s3_bucket.assets" in anchor.description


def test_strips_attribute_access_to_base(handler: TerraformHandler, tmp_path: Path) -> None:
    f = tmp_path / "ref.tf"
    f.write_text(
        """
resource "aws_lambda_function" "api" {
  role          = aws_iam_role.lambda_role.arn
  region_setting = var.region
  ami           = data.aws_ami.ubuntu.id
}
"""
    )
    _entities, rels = handler.extract(f)
    targets = {r.target_name for r in rels}
    assert "aws_iam_role.lambda_role" in targets  # .arn stripped
    assert "var.region" in targets
    assert "data.aws_ami.ubuntu" in targets  # .id stripped


def test_meta_args_not_referenced(handler: TerraformHandler, tmp_path: Path) -> None:
    f = tmp_path / "meta.tf"
    f.write_text(
        """
resource "aws_instance" "web" {
  count = 3
  name  = "web-${count.index}"
  self  = self.id
}
"""
    )
    _entities, rels = handler.extract(f)
    targets = {r.target_name for r in rels}
    assert not any(t.startswith("count.") for t in targets)
    assert not any(t.startswith("self.") for t in targets)


def test_dangling_targets_allowed(handler: TerraformHandler, tmp_path: Path) -> None:
    # A reference to an entity not declared in this file is still emitted; the
    # resolver drops dangling edges. We do NOT synthesize a node for it.
    f = tmp_path / "lambda.tf"
    f.write_text(
        """
resource "aws_lambda_function" "api" {
  filename = data.archive_file.lambda_zip.output_path
}
"""
    )
    entities, rels = handler.extract(f)
    names = {e.name for e in entities}
    assert "data.archive_file.lambda_zip" not in names  # not synthesized
    targets = {r.target_name for r in rels}
    assert "data.archive_file.lambda_zip" in targets  # edge still emitted


_REAL_LAMBDA = Path(
    "test-repos/vibe-coded/sudoku/terraform/lambda.tf"
)


@pytest.mark.skipif(
    not _REAL_LAMBDA.exists(), reason="real sudoku terraform corpus not present"
)
def test_real_sudoku_lambda(handler: TerraformHandler) -> None:
    entities, rels = handler.extract(_REAL_LAMBDA)
    names = {e.name for e in entities}
    assert "lambda" in names  # anchor
    assert "aws_lambda_function.api" in names
    assert "aws_iam_role.lambda_role" in names
    # cross-resource reference inside the file
    edges = {(r.source_name, r.target_name) for r in rels}
    assert ("aws_iam_role.lambda_role" not in names) or (
        ("aws_lambda_function.api", "aws_iam_role.lambda_role") in edges
    )
