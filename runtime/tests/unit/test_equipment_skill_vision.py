from __future__ import annotations

import hashlib
from copy import deepcopy
from pathlib import Path

import pytest
from PIL import Image

from utils.equipment_skill_vision import (
    apply_visual_locator_annotations,
    build_temporal_storyboards,
    collect_visual_annotation_evidence,
    resolve_visual_locator_source,
    strip_inline_image_payloads,
)


def _package(frame_path: Path) -> dict:
    digest = hashlib.sha256(frame_path.read_bytes()).hexdigest()
    return {
        "workflow": {
            "steps": [
                {
                    "step_id": "step-001",
                    "action": {
                        "action": "click",
                        "target": "evt-0001-target",
                        "recorded_coordinate": [100, 50],
                        "image_candidates": [],
                    },
                }
            ]
        },
        "recording": {
            "events": [
                {
                    "kind": "mouse_click",
                    "visual_locator": {
                        "locator_id": "evt-0001-target",
                        "full_frame_artifact_path": str(frame_path),
                        "full_frame_sha256": digest,
                    },
                }
            ]
        },
    }


def test_collect_visual_evidence_uses_verified_pre_action_frame(tmp_path: Path) -> None:
    frame = tmp_path / "evt-0001-source-frame.png"
    Image.new("RGB", (200, 100), "white").save(frame)

    evidence = collect_visual_annotation_evidence(_package(frame), allowed_roots=[tmp_path])

    assert len(evidence.images) == 1
    assert evidence.images[0].data == frame.read_bytes()
    assert evidence.steps == [
        {
            "image_index": 1,
            "step_id": "step-001",
            "locator_id": "evt-0001-target",
            "image_size": [200, 100],
            "recorded_coordinate_norm": [0.5, 0.5],
        }
    ]


def test_collect_visual_evidence_builds_chronological_action_state_flow(tmp_path: Path) -> None:
    initial = tmp_path / "initial.jpg"
    pre_click = tmp_path / "evt-0001-source-frame.png"
    after_click = tmp_path / "after-click.jpg"
    Image.new("RGB", (200, 100), "gray").save(initial)
    Image.new("RGB", (200, 100), "white").save(pre_click)
    Image.new("RGB", (200, 100), "green").save(after_click)
    package = _package(pre_click)
    package["recording"]["events"][0]["at_ms"] = 1000
    package["manifest"] = {
        "recording_evidence": {
            "frames": [
                {
                    "frame_id": "frame-initial",
                    "at_ms": 0,
                    "artifact_path": str(initial),
                    "sha256": hashlib.sha256(initial.read_bytes()).hexdigest(),
                    "media_type": "image/jpeg",
                    "width": 200,
                    "height": 100,
                    "reason": "boundary",
                },
                {
                    "frame_id": "frame-after-click",
                    "at_ms": 1300,
                    "artifact_path": str(after_click),
                    "sha256": hashlib.sha256(after_click.read_bytes()).hexdigest(),
                    "media_type": "image/jpeg",
                    "width": 200,
                    "height": 100,
                    "reason": "state_change",
                },
            ]
        }
    }

    evidence = collect_visual_annotation_evidence(package, allowed_roots=[tmp_path], max_images=8)

    assert [item["role"] for item in evidence.timeline] == [
        "initial_state",
        "pre_action",
        "post_action_state",
    ]
    assert [item["at_ms"] for item in evidence.timeline] == [0, 1000, 1300]
    assert evidence.timeline[1]["step_id"] == "step-001"
    assert evidence.timeline[1]["action"] == "click"
    assert evidence.timeline[2]["after_step_id"] == "step-001"
    assert [item["image_index"] for item in evidence.timeline] == [1, 2, 3]
    assert evidence.steps[0]["image_index"] == 2


def test_collect_visual_evidence_deduplicates_identical_timeline_frames(tmp_path: Path) -> None:
    frame = tmp_path / "same.png"
    Image.new("RGB", (200, 100), "white").save(frame)
    package = _package(frame)
    digest = hashlib.sha256(frame.read_bytes()).hexdigest()
    package["manifest"] = {
        "recording_evidence": {
            "frames": [
                {
                    "frame_id": "duplicate",
                    "at_ms": 1200,
                    "artifact_path": str(frame),
                    "sha256": digest,
                    "media_type": "image/png",
                    "width": 200,
                    "height": 100,
                }
            ]
        }
    }

    evidence = collect_visual_annotation_evidence(package, allowed_roots=[tmp_path])

    assert len(evidence.images) == 1
    assert len(evidence.timeline) == 1


def test_apply_visual_annotation_builds_bounded_runtime_locator(tmp_path: Path) -> None:
    frame = tmp_path / "evt-0001-source-frame.png"
    Image.new("RGB", (200, 100), "white").save(frame)
    package = _package(frame)
    updates = {
        "steps": [
            {
                "step_id": "step-001",
                "locator": {
                    "search_roi_norm": [0.1, 0.1, 0.6, 0.7],
                    "target_bbox_norm": [0.4, 0.4, 0.2, 0.2],
                    "context_bbox_norm": [0.25, 0.2, 0.5, 0.5],
                },
            }
        ]
    }

    enriched = apply_visual_locator_annotations(package, updates, allowed_roots=[tmp_path])
    action = enriched["workflow"]["steps"][0]["action"]

    assert action["region_normalized"] == [0.1, 0.1, 0.6, 0.7]
    assert [(item["kind"], item["width"], item["height"]) for item in action["image_candidates"]] == [
        ("tight", 40, 20),
        ("context", 100, 50),
    ]
    assert action["image_candidates"][0]["crop_origin"] == [80, 40]
    assert action["image_candidates"][0]["png_base64"]


def test_locator_source_recovers_ai_bbox_from_recorded_candidate(tmp_path: Path) -> None:
    frame = tmp_path / "evt-0001-source-frame.png"
    Image.new("RGB", (200, 100), "white").save(frame)
    package = _package(frame)
    package["recording"]["events"][0]["visual_locator"]["candidates"] = [
        {
            "kind": "tight",
            "width": 40,
            "height": 20,
            "crop_origin": [80, 40],
        }
    ]
    package["workflow"]["steps"][0]["action"].update(
        {
            "target_bbox_norm": [0.2, 0.1, 0.3, 0.4],
            "locator_origin": "manual_crop",
        }
    )
    package["annotations"] = {
        "steps": [
            {
                "step_id": "step-001",
                "locator": {
                    "target_bbox_norm": [0.2, 0.1, 0.3, 0.4],
                    "locator_origin": "manual_crop",
                },
            }
        ]
    }

    source = resolve_visual_locator_source(package, "step-001", allowed_roots=[tmp_path])

    assert source is not None
    assert source["target_bbox_norm"] == [0.2, 0.1, 0.3, 0.4]
    assert source["ai_target_bbox_norm"] == [0.4, 0.4, 0.2, 0.2]


def test_collect_visual_evidence_rejects_path_outside_allowed_roots(tmp_path: Path) -> None:
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    frame = tmp_path / "outside.png"
    Image.new("RGB", (20, 20), "white").save(frame)

    evidence = collect_visual_annotation_evidence(_package(frame), allowed_roots=[allowed])

    assert evidence.images == []
    assert evidence.steps == []


def test_prompt_payload_strips_duplicate_inline_base64() -> None:
    payload = {"image_candidates": [{"png_base64": "very-large", "sha256": "abc"}]}

    assert strip_inline_image_payloads(payload) == {
        "image_candidates": [{"png_base64": "<omitted:abc>", "sha256": "abc"}]
    }


def test_build_temporal_storyboards_covers_complete_two_fps_timeline(tmp_path: Path) -> None:
    frames = []
    for index in range(34):
        path = tmp_path / f"frame-{index + 1:08d}.jpg"
        Image.new("RGB", (320, 180), (index * 7 % 255, 80, 120)).save(path, quality=90)
        frames.append(
            {
                "frame_id": f"frame-{index + 1:08d}",
                "at_ms": index * 500,
                "artifact_path": str(path),
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "media_type": "image/jpeg",
                "width": 320,
                "height": 180,
                "reason": "periodic",
            }
        )
    package = {
        "recording": {
            "events": [
                {"kind": "mouse_click", "at_ms": 1000, "x": 120, "y": 80},
                {"kind": "key_press", "at_ms": 8500, "key": "enter"},
            ]
        },
        "manifest": {"recording_evidence": {"fps": 2.0, "frames": frames}},
    }

    bundle = build_temporal_storyboards(
        package,
        allowed_roots=[tmp_path],
        output_dir=tmp_path / "storyboards",
    )

    assert [len(chunk.tiles) for chunk in bundle.chunks] == [16, 16, 2]
    assert bundle.source_frame_count == 34
    assert bundle.covered_frame_ids == [item["frame_id"] for item in frames]
    assert all(chunk.image.data.startswith(b"\xff\xd8") for chunk in bundle.chunks)
    assert all(Path(chunk.path).is_file() for chunk in bundle.chunks)
    assert bundle.chunks[0].start_ms == 0
    assert bundle.chunks[0].end_ms == 7500
    assert bundle.chunks[1].tiles[1]["event"]["kind"] == "key_press"
    assert bundle.overview_images
    assert all(item["source_sha256"] == frames[index]["sha256"] for index, item in enumerate(bundle.chunks[0].tiles))


def test_storyboards_bound_fifteen_fps_evidence_and_keep_event_neighbors(tmp_path: Path) -> None:
    frame = tmp_path / "source.jpg"
    Image.new("RGB", (200, 100), "white").save(frame)
    digest = hashlib.sha256(frame.read_bytes()).hexdigest()
    frames = [
        {"frame_id": f"f-{index}", "at_ms": round(index * 1000 / 15),
         "artifact_path": str(frame), "sha256": digest, "reason": "periodic"}
        for index in range(450)
    ]
    frames[300]["reason"] = "state_change"
    package = {"recording": {"events": [{"kind": "mouse_click", "at_ms": 10000}]},
               "manifest": {"recording_evidence": {"fps": 15, "frames": frames}}}
    original = deepcopy(package)

    bundle = build_temporal_storyboards(package, allowed_roots=[tmp_path],
                                       output_dir=tmp_path / "storyboards", max_frames=12)

    assert bundle.source_frame_count == 450
    assert len(bundle.covered_frame_ids) == 12
    assert {"f-0", "f-449", "f-149", "f-150", "f-151", "f-300"} <= set(bundle.covered_frame_ids)
    assert bundle.event_coverage_complete is True
    assert bundle.omitted_event_numbers == []
    assert package == original
    assert frame.read_bytes() and hashlib.sha256(frame.read_bytes()).hexdigest() == digest


def test_storyboard_budget_reports_uncovered_events_instead_of_claiming_full_analysis(tmp_path: Path) -> None:
    frame = tmp_path / "source.jpg"
    Image.new("RGB", (200, 100), "white").save(frame)
    digest = hashlib.sha256(frame.read_bytes()).hexdigest()
    package = {
        "recording": {"events": [{"kind": "mouse_click", "at_ms": index * 1000 + 500}
                                  for index in range(20)]},
        "manifest": {"recording_evidence": {"frames": [
            {"frame_id": f"f-{index}", "at_ms": index * 100,
             "artifact_path": str(frame), "sha256": digest}
            for index in range(201)
        ]}},
    }

    bundle = build_temporal_storyboards(package, allowed_roots=[tmp_path],
                                       output_dir=tmp_path / "storyboards", max_frames=8)

    assert len(bundle.covered_frame_ids) == 8
    assert bundle.event_coverage_complete is False
    assert bundle.omitted_event_numbers


def test_storyboards_include_event_only_evidence_with_source_identity(tmp_path: Path) -> None:
    frame = tmp_path / "event.png"
    Image.new("RGB", (200, 100), "white").save(frame)
    package = {
        "recording": {"events": [{"kind": "key_press", "at_ms": 500, "key": "enter"}]},
        "manifest": {"recording_evidence": {"frames": [], "event_frames": [
            {"frame_id": "evt-1-post", "at_ms": 550, "event_at_ms": 500,
             "event_number": 1, "reason": "post_action", "artifact_path": str(frame),
             "sha256": hashlib.sha256(frame.read_bytes()).hexdigest()}
        ]}},
    }

    bundle = build_temporal_storyboards(package, allowed_roots=[tmp_path], output_dir=tmp_path / "storyboards")

    assert bundle.covered_frame_ids == ["evt-1-post"]
    assert bundle.chunks[0].tiles[0]["event"]["kind"] == "key_press"
    assert bundle.chunks[0].tiles[0]["role"] == "post_action"


def test_storyboards_merge_event_linkage_without_double_sampling_or_timestamp_rewrite(tmp_path: Path) -> None:
    frames = []
    for frame_id, at_ms, reason in [("initial", 0, "boundary"), ("event-0001", 450, "event"), ("final", 1000, "boundary")]:
        path = tmp_path / f"{frame_id}.png"
        Image.new("RGB", (200, 100), "white").save(path)
        frames.append({"frame_id": frame_id, "at_ms": at_ms, "reason": reason,
                       "artifact_path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
    linkage = {"event_number": 1, "at_ms": 100, "event_at_ms": 100, "captured_at_ms": 450,
               "event_frame_id": "event-0001", "artifact_path": f"{tmp_path}/./event-0001.png",
               "sha256": frames[1]["sha256"], "status": "ready"}
    package = {"recording": {"events": [{"kind": "mouse_click", "at_ms": 100}]},
               "manifest": {"recording_evidence": {"frames": frames, "event_frames": [linkage]}}}
    original = deepcopy(package)

    bundle = build_temporal_storyboards(package, allowed_roots=[tmp_path],
                                       output_dir=tmp_path / "storyboards", max_frames=3)

    assert bundle.source_frame_count == 3
    assert bundle.covered_frame_ids == ["initial", "event-0001", "final"]
    assert bundle.event_coverage_complete is True
    event_tile = bundle.chunks[0].tiles[1]
    assert event_tile["at_ms"] == 450
    assert event_tile["event"] == {"kind": "mouse_click", "at_ms": 100}
    assert package == original


def test_storyboards_keep_partial_recording_reviewable_when_event_capture_failed(tmp_path: Path) -> None:
    path = tmp_path / "available.png"
    Image.new("RGB", (200, 100), "white").save(path)
    package = {"recording": {"events": [{"kind": "mouse_click", "at_ms": 100}]}, "manifest": {
        "recording_evidence": {"frames": [{"frame_id": "available", "at_ms": 0,
            "artifact_path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}],
            "event_frames": [{"event_number": 1, "event_at_ms": 100, "status": "failed",
                "failure_code": "RECORDING_QUEUE_OVERLOAD", "event_frame_id": "", "artifact_path": ""}]}}}

    bundle = build_temporal_storyboards(package, allowed_roots=[tmp_path], output_dir=tmp_path / "storyboards")

    assert bundle.covered_frame_ids == ["available"]
    assert bundle.source_frame_count == 1
    assert bundle.event_coverage_complete is False
    assert bundle.omitted_event_numbers == [1]


def test_storyboards_do_not_hide_corrupt_available_event_images(tmp_path: Path) -> None:
    path = tmp_path / "corrupt.png"
    Image.new("RGB", (200, 100), "white").save(path)
    package = {"manifest": {"recording_evidence": {"frames": [], "event_frames": [{
        "event_number": 1, "at_ms": 100, "artifact_path": str(path), "sha256": "0" * 64,
        "status": "ready"}]}}}

    with pytest.raises(ValueError, match="unverified timeline frame"):
        build_temporal_storyboards(package, allowed_roots=[tmp_path], output_dir=tmp_path / "storyboards")
