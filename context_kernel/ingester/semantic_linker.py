"""Stage 4 (ADR-0017): embedding-assisted recall layer — `related` edges, gated.

A fuzzy recall layer on top of the precise typed graph: connects doc concept nodes to
the code they are semantically about, when name/contextual extraction missed it. Edges
are tagged `related` (not a typed extracted edge) and gated hard against the
"confabulation engine" ADR-0009 warns about: mutual k-NN + cosine threshold + per-node cap.
Never merges identity — discovery is too fuzzy for that; this only adds edges.
"""

from __future__ import annotations

import numpy as np


def semantic_links(
    node_ids: list[str],
    embeddings: np.ndarray,          # (n, dim) float32, row i ↔ node_ids[i]
    is_code: list[bool],
    existing_edges: set[tuple[str, str]],
    *,
    k: int = 5,
    threshold: float = 0.78,
    max_per_node: int = 3,
) -> list[tuple[str, str, float]]:
    """Return (concept_id, code_id, cosine) for mutual-k-NN concept↔code pairs above threshold."""
    concept_idx = [i for i, c in enumerate(is_code) if not c]
    code_idx = [i for i, c in enumerate(is_code) if c]
    if not concept_idx or not code_idx:
        return []

    norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
    unit = embeddings / np.clip(norms, 1e-8, None)
    Q = unit[concept_idx]            # (nq, dim)
    C = unit[code_idx]               # (nc, dim)
    M = Q @ C.T                      # (nq, nc) cosine

    kc = min(k, C.shape[0])
    kq = min(k, Q.shape[0])
    topk_code = np.argpartition(-M, kth=kc - 1, axis=1)[:, :kc]        # code ranks per concept
    topk_conc = np.argpartition(-M, kth=kq - 1, axis=0)[:kq, :]        # concept ranks per code
    code_to_top_concepts = [set(topk_conc[:, j].tolist()) for j in range(M.shape[1])]

    out: list[tuple[str, str, float]] = []
    for qi in range(M.shape[0]):
        cands = [
            (cj, float(M[qi, cj]))
            for cj in topk_code[qi]
            if M[qi, cj] >= threshold and qi in code_to_top_concepts[cj]   # mutual k-NN
        ]
        cands.sort(key=lambda x: -x[1])
        for cj, score in cands[:max_per_node]:
            cid, kid = node_ids[concept_idx[qi]], node_ids[code_idx[cj]]
            if (cid, kid) in existing_edges or (kid, cid) in existing_edges:
                continue
            out.append((cid, kid, score))
    return out
