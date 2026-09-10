"""Closed observation classes, never a transform, grade or history approval.

The original class remains byte/request compatible. The explicit v2 class
observes original UHD xvYCC-tagged frames; it does not interpret their gamut,
infer BT.709 transfer, or validate the operator's camera/history declaration.
"""
from __future__ import annotations

from dataclasses import dataclass

from color.grade_contract import (
    GradeDeclaration, SourceBinding, _groups, _text, closed, integer, parse_declaration,
)
from cut_preview_io import digest

V2_PROFILE = "original-uhd-xvycc709-observation-v2"
V1_POLICY = "sniper-private-grade-observation-v1"
V2_POLICY = "sniper-private-grade-observation-v2"
V1_PROJECT_POLICY = "sniper-private-project-source-observation-v1"
V2_PROJECT_POLICY = "sniper-private-project-source-observation-v2"


@dataclass(frozen=True)
class ObservationProfile:
    """Code-owned limits; no request may supply its own resource policy."""

    token: str | None
    version: int
    policy: str
    project_policy: str
    max_source_bytes: int
    max_frames: int
    max_width: int
    max_height: int
    max_pixels: int
    max_seconds: int
    threads: int
    transfer: str

    def evidence(self) -> dict:
        """Only v2 adds these closed limits to its receipt, never to v1."""
        if self.token is None:
            return {}
        return {"profile": self.token, "limits": {
            "maxSourceBytes": self.max_source_bytes, "maxFrames": self.max_frames,
            "maxWidth": self.max_width, "maxHeight": self.max_height,
            "maxDecodedPixels": self.max_pixels, "maxWorkSeconds": self.max_seconds,
            "decoderThreads": self.threads, "cpus": 4, "memoryMiB": 768,
            "maxRecordBytes": 128 * 1024 ** 2, "cleanupSeconds": 90}}


V1 = ObservationProfile(None, 1, V1_POLICY, V1_PROJECT_POLICY, 8 * 1024 ** 3,
                        1_296_000, 8192, 8192, 37_324_800_000, 120, 1, "bt709")
V2 = ObservationProfile(V2_PROFILE, 2, V2_POLICY, V2_PROJECT_POLICY, 16 * 1024 ** 3,
                        24_000, 3840, 2160, 199_065_600_000, 1200, 4, "iec61966-2-4")


def observation_profile(token: object = None) -> ObservationProfile:
    """An absent profile means only the unchanged legacy class."""
    if token is None:
        return V1
    if type(token) is str and token == V2_PROFILE:
        return V2
    raise ValueError("grade observation profile is unsupported")


def project_profile(value: dict) -> ObservationProfile:
    """Require the version/policy/profile together; no historical upgrading."""
    profile = observation_profile(value.get("profile"))
    if type(value.get("schemaVersion")) is not int or value["schemaVersion"] != profile.version \
            or value.get("policy") != profile.project_policy \
            or (profile is V1 and "profile" in value):
        raise ValueError("project observation version/profile is inconsistent")
    return profile


def parse_request(value: object) -> dict:
    """Bound source/count/time before IO; executable/runtime paths are forbidden."""
    if type(value) is not dict:
        raise ValueError("grade observation request is malformed")
    profile = observation_profile(value.get("profile"))
    keys = {"sourceSha256", "frameCount", "timeoutSeconds"}
    if profile is V2:
        keys |= {"schemaVersion", "profile"}
    row = closed(value, keys, "grade observation request")
    if profile is V2 and (type(row["schemaVersion"]) is not int or row["schemaVersion"] != 2):
        raise ValueError("grade observation request version is invalid")
    sha = row["sourceSha256"]
    if type(sha) is not str or len(sha) != 64 or any(char not in "abcdef0123456789" for char in sha):
        raise ValueError("grade observation source identity is invalid")
    integer(row["frameCount"], 1, profile.max_frames)
    integer(row["timeoutSeconds"], 30, profile.max_seconds)
    return dict(row)


def frame_budget(width: object, height: object, count: object, profile: ObservationProfile) -> None:
    """Cheap rejection only; these expectations do not prove a decoder ran."""
    width = integer(width, 2, profile.max_width)
    height = integer(height, 2, profile.max_height)
    count = integer(count, 1, profile.max_frames)
    if width % 2 or height % 2 or width * height * count > profile.max_pixels:
        raise ValueError("grade observation frame/pixel budget exceeded")


def admitted_facts(facts: dict, profile: ObservationProfile) -> None:
    """Match the verified receipt's full-source expectation before costly decode."""
    if facts.get("mediaKind") != "timed-media" or type(facts.get("videoStreams")) is not int \
            or facts["videoStreams"] != 1:
        raise ValueError("grade observation requires one admitted video stream")
    integer(facts.get("sizeBytes"), 1, profile.max_source_bytes)
    if profile is V2:
        integer(facts.get("streamCount"), 1, 32)
    frame_budget(facts.get("width"), facts.get("height"), facts.get("declaredFrames"), profile)


def observation_declaration(value: object, binding: SourceBinding,
                            profile: ObservationProfile) -> GradeDeclaration:
    """Retain explicit unknown history/profile without granting grading power."""
    if profile is V1:
        return parse_declaration(value, binding)
    keys = {"schemaVersion", "sourceId", "sourceProfile", "cameraProfile",
            "historyState", "transformHistory", "lightingGroups"}
    row = closed(value, keys, "v2 observation declaration")
    if type(row["schemaVersion"]) is not int or row["schemaVersion"] != 2 \
            or row["sourceId"] != binding.source_id or digest(row) != binding.declaration_sha256:
        raise ValueError("v2 observation declaration differs from its source binding")
    if row["sourceProfile"] not in ("xvycc709", "unknown") or row["historyState"] not in ("known", "unknown"):
        raise ValueError("v2 observation declaration profile/history is unsupported")
    camera = None if row["cameraProfile"] is None else _text(row["cameraProfile"], 200, False)
    history = row["transformHistory"]
    if type(history) is not list or len(history) > 20:
        raise ValueError("v2 observation history exceeds its bound")
    return GradeDeclaration(binding.source_id, camera, tuple(_text(item, 500, False) for item in history),
                            _groups(row["lightingGroups"], binding.frame_count))
