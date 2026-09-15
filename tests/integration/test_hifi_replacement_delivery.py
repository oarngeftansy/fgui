from __future__ import annotations

from pathlib import Path

from scripts.run_hifi_replacement_acceptance import run_acceptance


def test_hifi_replacement_delivery_preserves_scope_and_candidate_hash(tmp_path: Path) -> None:
    workspace = Path(__file__).parents[2]
    result = run_acceptance(workspace, tmp_path / "candidate.zip")
    assert result["automatedStatus"] == "PASS"
    assert result["scopeValid"] is True
    assert result["protectedIdentityUnchanged"] is True
    assert result["sharedReferenceUnchanged"] is True
    assert result["lowfiReferenceReplaced"] is True
    assert result["hifiResourceRegistered"] is True
    assert result["hifiResourceBytesMatch"] is True
    assert result["candidateEqualsDelivered"] is True
    assert result["candidateSha256"] == result["deliveredSha256"] == result["reviewSha256"]
    assert result["archiveContainsTarget"] is True
    assert result["decisionCounts"] == {
        "accept": 4,
        "add_visual": 1,
        "exception": 2,
        "keep_old": 2,
        "retarget": 1,
    }
    assert result["objectDiffCounts"] == {
        "added": 1,
        "changed": 5,
        "exception": 2,
        "kept": 2,
    }
