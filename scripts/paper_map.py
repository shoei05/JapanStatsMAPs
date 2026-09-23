"""Build complete topic membership without inventing exposure/outcome relationships."""
from collections import Counter, defaultdict
from pathlib import PurePosixPath


def classification_documents(documents, document_kinds, kind_for_name):
    """Prefer original articles even when an attached appendix contains more text."""
    originals = [path for path in documents
                 if document_kinds.get(path, kind_for_name(PurePosixPath(path).name)) == "paper"]
    return originals or documents


def classification_tags(record):
    # A reviewed empty list is meaningful and must not revive old machine tags.
    return record["tags_yes_final"] if "tags_yes_final" in record else record.get("tags_yes") or []


def build_paper_map(papers, domains, reviews=None, separate_domains=()):
    reviews = reviews or {}
    valid = set(domains)
    separate = set(separate_domains)
    pairs, membership = defaultdict(set), defaultdict(set)
    excluded, unmapped = Counter(), []
    for paper in papers:
        if paper.get("doc_kind") != "paper":
            continue
        pid = paper["paper_id"]
        review = reviews.get(pid, {})
        explicit_pairs = review.get("analysis_pairs")
        if explicit_pairs is not None:
            # An explicitly reviewed empty list means there is no exposure/outcome edge.
            candidates = []
            for pair in explicit_pairs:
                if not pair.get("evidence"):
                    raise ValueError(f"Reviewed analysis pair requires evidence: {pid}")
                e, o = pair["exposure"], pair["outcome"]
                if e not in valid or o not in valid:
                    raise ValueError(f"Unknown reviewed analysis domain: {pid}: {e}|{o}")
                candidates.append((e, o))
        elif paper.get("question_type") == "association":
            candidates = [(paper.get("exposure_domain"), paper.get("outcome_domain"))]
        else:
            candidates = []
        accepted = {(e, o) for e, o in candidates if e in valid and o in valid
                    and e not in separate and o not in separate}
        if "map_domains" in review:
            if not review.get("evidence"):
                raise ValueError(f"Reviewed topic membership requires evidence: {pid}")
            topics = set(review["map_domains"])
            if not topics <= valid:
                raise ValueError(f"Unknown reviewed topic: {pid}: {topics - valid}")
        else:
            topics = {paper.get("exposure_domain"), paper.get("outcome_domain"),
                      *(paper.get("tags") or [])} & valid
        # 本文確認で追加したテーマ（新設テーマの再点検など）。機械分類・既存レビューのテーマに上乗せする。
        for added in review.get("added_domains", []):
            if not added.get("evidence") or added.get("domain") not in valid:
                raise ValueError(f"Added topic requires a known domain and evidence: {pid}: {added}")
            topics.add(added["domain"])
        # Every edge is reachable through both topic nodes, even after a review override.
        topics.update(d for pair in accepted for d in pair)
        paper["map_domains"] = sorted(topics)
        paper["map_status"] = "association" if accepted else "topic" if topics else "unclassified"
        for domain in topics:
            membership[domain].add(pid)
        for e, o in accepted:
            pairs[f"{e}|{o}"].add(pid)
        if not accepted:
            excluded[paper.get("question_type") or "unknown"] += 1
        if not topics:
            unmapped.append(pid)
    result = {
        "pairs": {k: sorted(v) for k, v in sorted(pairs.items(), key=lambda x: (-len(x[1]), x[0]))},
        "domain_papers": {k: sorted(v) for k, v in sorted(membership.items())},
        "unmapped_papers": sorted(unmapped),
        "pairs_excluded": dict(excluded),
    }
    expected = {p["paper_id"] for p in papers if p.get("doc_kind") == "paper"}
    covered = set().union(*membership.values()) if membership else set()
    assert covered.isdisjoint(unmapped)
    assert covered | set(unmapped) == expected, "A paper was lost from the map"
    return result
