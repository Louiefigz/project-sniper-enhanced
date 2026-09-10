"""Shared P4 scene fixtures with stable authority identities."""
from __future__ import annotations


def fire_sparkles_scene(bundle_hash: str,
                        right_title: str = "Change only this card") -> dict:
    """Two independently addressable units beginning at output second 45."""
    variables = {
        "leftTitle": "Blue card with deterministic fire",
        "rightTitle": right_title,
        "leftColor": "#0B5FFF",
        "seed": 424242,
        "fireIntensity": 1,
        "sparkleCount": 22,
    }
    return {
        "schemaVersion": 1,
        "sceneId": "scene-045",
        "version": 1,
        "timing": {
            "startFrame": 1350,
            "endFrameExclusive": 1530,
            "fps": {"numerator": "30", "denominator": "1"},
            "timelineMapHash": "a" * 64,
        },
        "canvas": {"width": 1920, "height": 1080},
        "renderMode": "overlay-alpha",
        "composition": {
            "type": "project",
            "bundleId": "fire-sparkles-cards",
            "bundleHash": bundle_hash,
            "entry": "compositions/full.html",
            "variables": variables,
        },
        "elements": [
            {
                "elementId": "left-blue-card",
                "role": "information-card",
                "exposedProperties": ["leftTitle", "leftColor"],
                "values": {
                    "leftTitle": variables["leftTitle"],
                    "leftColor": variables["leftColor"],
                },
            },
            {
                "elementId": "seeded-fire",
                "role": "decorative-fire",
                "exposedProperties": ["seed", "fireIntensity"],
                "values": {
                    "seed": variables["seed"],
                    "fireIntensity": variables["fireIntensity"],
                },
            },
            {
                "elementId": "right-copy",
                "role": "information-card",
                "exposedProperties": ["rightTitle"],
                "values": {"rightTitle": variables["rightTitle"]},
            },
            {
                "elementId": "seeded-sparkles",
                "role": "decorative-sparkles",
                "exposedProperties": ["seed", "sparkleCount"],
                "values": {
                    "seed": variables["seed"],
                    "sparkleCount": variables["sparkleCount"],
                },
            },
        ],
        "renderUnits": [
            {
                "unitId": "unit-left",
                "elementIds": ["left-blue-card", "seeded-fire"],
                "zIndex": 10,
                "entry": "compositions/unit-left.html",
                "compositeMode": "normal",
                "palmierGranularity": "unit",
            },
            {
                "unitId": "unit-right",
                "elementIds": ["right-copy", "seeded-sparkles"],
                "zIndex": 20,
                "entry": "compositions/unit-right.html",
                "compositeMode": "normal",
                "palmierGranularity": "unit",
            },
        ],
        "captionPolicy": "suppress-overlap",
        "dependencies": [],
        "provenance": {
            "origin": "operator",
            "requestId": "request-fire-sparkles",
        },
    }
