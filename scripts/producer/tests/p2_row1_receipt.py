"""Path-free retained evidence extraction for the P2 row-one cohort."""
from __future__ import annotations

from edit.picture_lock_common import content_hash
from palmier.cut_repair_projection import verify_cut_repair_readback
from palmier.mcp_client import PalmierError
from tests.p2_row1_caption_fixture import TOTAL_FRAMES

_POSITIONS = ("early", "middle", "late")


def _blocked_readback(disposition: dict) -> dict:
    try:
        verify_cut_repair_readback(disposition, {}, {})
    except PalmierError as exc:
        return {
            "verificationAttempted": True,
            "verificationStatus": "rejected-before-native-readback",
            "mutationAttempted": False,
            "error": str(exc),
        }
    return {
        "verificationAttempted": True,
        "verificationStatus": "unexpectedly-accepted",
        "mutationAttempted": False,
        "error": None,
    }


def media_evidence(result: dict) -> dict:
    """Distill real fragment/master proof without retaining temporary paths."""
    fragment = result["fragmentReceipt"]
    composite = result["compositeReceipt"]
    return {
        "fragmentReceiptHash": content_hash(fragment),
        "fragmentOutputSha256": fragment["output"]["sha256"],
        "fragmentVideoFrames": fragment["output"]["videoFrames"],
        "fragmentAudioSamplesPerChannel":
            fragment["output"]["audioSamplesPerChannel"],
        "sourceTimingClass":
            fragment["inputs"]["source"]["timingClass"],
        "sourceSha256": fragment["inputs"]["source"]["sha256"],
        "parentSha256": fragment["inputs"]["parent"]["sha256"],
        "compositeReceiptHash": content_hash(composite),
        "masterSha256": composite["output"]["sha256"],
        "masterVideoFrames": composite["output"]["videoFrames"],
        "masterAudioSamplesPerChannel":
            composite["output"]["audioSamplesPerChannel"],
        "terminalExpectedSamples": composite["terminalExpectedSamples"],
        "outsideDirtyOracle": composite["outsideDirtyOracle"],
    }


def caption_evidence(result: dict, metadata: dict) -> dict:
    """Distill the actual before/after caption compiler revalidation."""
    receipt = result["captionRevalidation"]
    cues = receipt["cues"]
    return {
        **metadata,
        "status": receipt["status"],
        "revalidationHash": receipt["revalidationHash"],
        "authorizedDirtyWindows": receipt["authorizedDirtyWindows"],
        "changedCueIds": cues["changedCueIds"],
        "unchangedCueIds": cues["unchangedCueIds"],
        "contentNodesReused": cues["contentNodesReused"],
        "contentNodesRebuilt": cues["contentNodesRebuilt"],
        "beforeCompilationHash": receipt["beforeCompilationHash"],
        "afterCompilationHash": receipt["afterCompilationHash"],
    }


def palmier_evidence(result: dict) -> dict:
    """Bind projection plus an executable fail-closed readback attempt."""
    disposition = result["palmierDisposition"]
    return {
        "projectionHash": disposition["projectionHash"],
        "nativeStatus": disposition["nativeStatus"],
        "deliveryDisposition": disposition["deliveryDisposition"],
        "sampleExact": disposition["sampleExact"],
        "requiresRepairFragmentImport":
            disposition["requiresRepairFragmentImport"],
        "reason": disposition["reason"],
        "readback": _blocked_readback(disposition),
    }


def invariants(result: dict) -> dict:
    """Recompute every candidate-level evidence binding."""
    proof = result["invariantProof"]
    hashes_bound = (
        result["invariantProofHash"] == content_hash(proof)
        and proof["fragmentReceiptHash"]
        == content_hash(result["fragmentReceipt"])
        and proof["palmierDispositionHash"]
        == content_hash(result["palmierDisposition"])
        and proof["captionRevalidationHash"]
        == result["captionRevalidation"]["revalidationHash"]
        and proof["terminalCompositeReceiptHash"]
        == content_hash(result["compositeReceipt"])
    )
    return {
        "invariantProofHash": result["invariantProofHash"],
        "childPictureLockHash": result["childPictureLockHash"],
        "supersessionHash": result["supersessionHash"],
        "totalOutputFramesPreserved":
            proof["totalOutputFramesPreserved"],
        "terminalCompositeProved": proof["terminalCompositeProved"],
        "hashesBound": hashes_bound,
    }


def assertions(value: dict) -> dict[str, bool]:
    """Evaluate every claim dimension for one executed case."""
    media, captions = value["media"], value["captions"]
    dialogue, palmier = value["dialogue"], value["palmier"]
    oracle = media["outsideDirtyOracle"]
    return {
        "candidateProved": value["candidateStatus"] == "candidate-proved",
        "positionBound": value["repair"]["position"] in _POSITIONS,
        "normalizedVfr":
            media["sourceTimingClass"] == "normalized-from-vfr-source",
        "distinctMediaInputs":
            media["sourceSha256"] != media["parentSha256"],
        "multiSourceAuthority":
            value["authority"]["sourceIds"] == ["source-a", "source-b"],
        "captionRefit": captions["status"] == "revalidated",
        "oneCaptionCueChanged": len(captions["changedCueIds"]) == 1,
        "oneCaptionCueUnchanged": len(captions["unchangedCueIds"]) == 1,
        "captionContentReused":
            captions["changedCueIds"] == captions["contentNodesReused"],
        "generalJResolved":
            dialogue["jRoles"] == ["j-cut-handle", "primary"],
        "generalLResolved":
            dialogue["lRoles"] == ["primary", "l-cut-handle"],
        "dialogueCaptionsCompiled":
            dialogue["cueCount"] > 0
            and dialogue["renderedWordCount"] == 2,
        "localMasterFramesExact":
            media["masterVideoFrames"] == TOTAL_FRAMES,
        "terminalPcmExact":
            media["masterAudioSamplesPerChannel"]
            == media["terminalExpectedSamples"],
        "outsidePicturePreserved": oracle["pictureMatches"] is True,
        "outsidePcmPreserved": oracle["pcmMatches"] is True,
        "palmierNativeUnsupported":
            palmier["nativeStatus"] == "unsupported",
        "palmierBakedExact":
            palmier["deliveryDisposition"] == "baked-exact-master",
        "palmierNotSampleExact": palmier["sampleExact"] is False,
        "palmierReadbackFailClosed":
            palmier["readback"]["verificationStatus"]
            == "rejected-before-native-readback",
        "invariantHashesBound": value["invariants"]["hashesBound"],
        "totalFramesPreserved":
            value["invariants"]["totalOutputFramesPreserved"] is True,
    }
