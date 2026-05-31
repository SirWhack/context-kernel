"""Tests for the Bicep (Azure IaC) StructuredHandler."""

from __future__ import annotations

from pathlib import Path

import pytest

from context_kernel.ingester.bicep_handler import BicepHandler

# A realistic multi-resource Bicep template: param + var + storage account
# resource + an existing key-vault resource + a module call, with cross-
# references between them (symbolic-name joins).
_FIXTURE = """\
targetScope = 'resourceGroup'

@description('Azure region for all resources')
param location string = resourceGroup().location

@minLength(3)
param namePrefix string

var storageName = '${namePrefix}stor'

resource kv 'Microsoft.KeyVault/vaults@2023-07-01' existing = {
  name: '${namePrefix}-kv'
}

resource stg 'Microsoft.Storage/storageAccounts@2023-01-01' = {
  name: storageName
  location: location
  sku: {
    name: 'Standard_LRS'
  }
  kind: 'StorageV2'
}

module net 'modules/network.bicep' = {
  name: 'networkDeploy'
  params: {
    location: location
    prefix: namePrefix
  }
}

output storageId string = stg.id
output storageEndpoint string = stg.properties.primaryEndpoints.blob
output vaultUri string = kv.properties.vaultUri
output subnetId string = net.outputs.subnetId
"""


@pytest.fixture()
def bicep_file(tmp_path: Path) -> Path:
    p = tmp_path / "main.bicep"
    p.write_text(_FIXTURE, encoding="utf-8")
    return p


def _by_name(entities) -> dict[str, str]:
    return {e.name: e.kind for e in entities}


def test_supports_only_bicep(tmp_path: Path) -> None:
    h = BicepHandler()
    assert h.supports(tmp_path / "main.bicep")
    assert h.supports(tmp_path / "Main.BICEP")
    assert not h.supports(tmp_path / "main.tf")
    assert not h.supports(tmp_path / "main.py")


def test_empty_file_returns_nothing(tmp_path: Path) -> None:
    p = tmp_path / "empty.bicep"
    p.write_text("   \n\n", encoding="utf-8")
    entities, rels = BicepHandler().extract(p)
    assert entities == []
    assert rels == []


def test_anchor_module_entity(bicep_file: Path) -> None:
    entities, _ = BicepHandler().extract(bicep_file)
    module = entities[0]
    assert module.name == "main"
    assert module.kind == "module"
    # Description lists declared resources/params/outputs + Depth/LOC.
    assert "Microsoft.Storage/storageAccounts" in module.description
    assert "namePrefix" in module.description
    assert "storageEndpoint" in module.description
    assert "Depth:" in module.description
    assert "LOC" in module.description


def test_symbolic_names_and_kinds(bicep_file: Path) -> None:
    entities, _ = BicepHandler().extract(bicep_file)
    kinds = _by_name(entities)

    # Resources are named by their symbolic name (not their ARM type).
    assert kinds["stg"] == "resource"
    assert kinds["kv"] == "resource"
    # Params, vars, outputs, and module calls.
    assert kinds["location"] == "param"
    assert kinds["namePrefix"] == "param"
    assert kinds["storageName"] == "var"
    assert kinds["net"] == "module_call"
    assert kinds["storageId"] == "output"
    assert kinds["vaultUri"] == "output"


def test_resource_captures_arm_type_in_description(bicep_file: Path) -> None:
    entities, _ = BicepHandler().extract(bicep_file)
    stg = next(e for e in entities if e.name == "stg")
    assert "Microsoft.Storage/storageAccounts" in stg.description


def test_existing_resource_noted(bicep_file: Path) -> None:
    entities, _ = BicepHandler().extract(bicep_file)
    kv = next(e for e in entities if e.name == "kv")
    assert kv.kind == "resource"
    assert "existing" in kv.description.lower()


def test_module_call_captures_path(bicep_file: Path) -> None:
    entities, _ = BicepHandler().extract(bicep_file)
    net = next(e for e in entities if e.name == "net")
    assert net.kind == "module_call"
    assert "modules/network.bicep" in net.description


def test_references_relationships(bicep_file: Path) -> None:
    _, rels = BicepHandler().extract(bicep_file)
    refs = {(r.source_name, r.target_name) for r in rels if r.kind == "references"}

    # storage account references the var (name) and param (location).
    assert ("stg", "storageName") in refs
    assert ("stg", "location") in refs
    # module call passes through the param.
    assert ("net", "location") in refs
    assert ("net", "namePrefix") in refs
    # outputs reference resources/modules — attribute tails stripped to base.
    assert ("storageId", "stg") in refs
    assert ("vaultUri", "kv") in refs
    assert ("subnetId", "net") in refs


def test_references_only_to_declared_symbolic_names(bicep_file: Path) -> None:
    _, rels = BicepHandler().extract(bicep_file)
    declared = {"location", "namePrefix", "storageName", "kv", "stg", "net",
                "storageId", "storageEndpoint", "vaultUri", "subnetId"}
    for r in rels:
        # Every reference target must be a symbolic name declared in the file
        # (this is how false positives from bare identifiers are bounded).
        assert r.target_name in declared, f"unexpected ref target {r.target_name!r}"
        # No reference to ARM-type fragments or built-ins.
        assert r.target_name not in {"Microsoft", "Standard_LRS", "StorageV2"}


def test_never_raises_on_garbage(tmp_path: Path) -> None:
    p = tmp_path / "broken.bicep"
    p.write_text("resource @@@ '''' = {{{{ \n param param param", encoding="utf-8")
    # Must not raise — returns whatever it could parse (possibly just defaults).
    entities, rels = BicepHandler().extract(p)
    assert isinstance(entities, list)
    assert isinstance(rels, list)
