"""Tests for the GraphQL SDL source handler."""

from __future__ import annotations

from pathlib import Path

from context_kernel.ingester.graphql_handler import GraphQLHandler
from context_kernel.ingester.handlers import RawRelationship


def _write(tmp_path: Path, name: str, text: str) -> Path:
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return p


def test_supports_suffixes():
    h = GraphQLHandler()
    assert h.supports(Path("schema.graphql"))
    assert h.supports(Path("schema.gql"))
    assert not h.supports(Path("schema.py"))
    assert not h.supports(Path("schema.ts"))


def test_extract_empty(tmp_path):
    h = GraphQLHandler()
    p = _write(tmp_path, "empty.graphql", "")
    assert h.extract(p) == ([], [])
    p2 = _write(tmp_path, "ws.graphql", "   \n  \n")
    assert h.extract(p2) == ([], [])


def test_extract_malformed_does_not_raise(tmp_path):
    h = GraphQLHandler()
    p = _write(tmp_path, "bad.graphql", "type {{{ broken : : (")
    ents, rels = h.extract(p)
    assert isinstance(ents, list)
    assert isinstance(rels, list)


FIXTURE = '''\
"""User account"""
type User {
  """primary id"""
  id: ID!
  email: String!
  game: SudokuGame
}

type SudokuGame {
  id: ID!
  owner: User!
  difficulty: Difficulty!
}

input CreateGameInput {
  difficulty: Difficulty!
  seed: String
}

enum Difficulty {
  EASY
  HARD
}

type Query {
  """Get a game"""
  game(id: ID!): SudokuGame
  me: User
}
'''


def test_extract_entities_and_kinds(tmp_path):
    h = GraphQLHandler()
    p = _write(tmp_path, "schema.graphql", FIXTURE)
    ents, _rels = h.extract(p)
    by_name = {e.name: e for e in ents}

    # Module anchor named after the file stem.
    assert by_name["schema"].kind == "module"

    # Object types.
    assert by_name["User"].kind == "type"
    assert by_name["SudokuGame"].kind == "type"

    # Input + enum.
    assert by_name["CreateGameInput"].kind == "input"
    assert by_name["Difficulty"].kind == "enum"

    # Query root + its operation fields as distinct entities.
    assert by_name["Query"].kind == "query"
    assert by_name["Query.game"].kind == "query_field"
    assert by_name["Query.me"].kind == "query_field"

    # Field listing in object description.
    assert "email: String!" in by_name["User"].description
    # Enum values listed.
    assert "EASY" in by_name["Difficulty"].description


def test_extract_relationships(tmp_path):
    h = GraphQLHandler()
    p = _write(tmp_path, "schema.graphql", FIXTURE)
    _ents, rels = h.extract(p)
    triples = {(r.source_name, r.target_name, r.kind) for r in rels}

    # Field reference: User.game -> SudokuGame.
    assert ("User", "SudokuGame", "references") in triples
    # SudokuGame.owner -> User and .difficulty -> Difficulty.
    assert ("SudokuGame", "User", "references") in triples
    assert ("SudokuGame", "Difficulty", "references") in triples
    # Input field referencing an enum.
    assert ("CreateGameInput", "Difficulty", "references") in triples
    # Query operation field references its return type.
    assert ("Query.game", "SudokuGame", "references") in triples
    assert ("Query.me", "User", "references") in triples

    # Built-in scalars are NOT referenced.
    targets = {r.target_name for r in rels}
    assert "ID" not in targets
    assert "String" not in targets


def test_implements_and_union(tmp_path):
    h = GraphQLHandler()
    text = (
        "interface Node {\n  id: ID!\n}\n\n"
        "type Post implements Node {\n  id: ID!\n  author: User\n}\n\n"
        "type User {\n  id: ID!\n}\n\n"
        "union SearchResult = Post | User\n"
    )
    p = _write(tmp_path, "s.graphql", text)
    ents, rels = h.extract(p)
    by_name = {e.name: e for e in ents}
    triples = {(r.source_name, r.target_name, r.kind) for r in rels}

    assert by_name["Node"].kind == "interface"
    assert by_name["SearchResult"].kind == "union"
    assert ("Post", "Node", "implements") in triples
    assert ("SearchResult", "Post", "references") in triples
    assert ("SearchResult", "User", "references") in triples
