"""Semantic partition proposals; never compiles, deploys, or executes equipment."""
from __future__ import annotations

from copy import deepcopy
import fcntl
from pathlib import Path
import shutil
import tempfile
from uuid import uuid4

from utils.equipment_skill_runtime import (
    EquipmentSkillRegistry, SkillContractError, _atomic_write_json, _now_iso,
    _read_json, _safe_identity, canonical_sha256, validate_skill_package,
)


def validate_partition(workflow: dict, payload: dict) -> dict:
    if not isinstance(payload, dict) or set(payload) - {"parts", "branches"}:
        raise SkillContractError("split proposal must contain only parts and branches")
    parts = payload.get("parts")
    if not isinstance(parts, list) or not 1 <= len(parts) <= 32:
        raise SkillContractError("split proposal requires 1–32 parts")
    normalized = []
    for part in parts:
        if not isinstance(part, dict) or set(part) - {"name", "step_ids", "purpose", "preconditions", "postconditions"}:
            raise SkillContractError("parts may describe boundaries, not add actions")
        ids = part.get("step_ids")
        if not isinstance(ids, list) or not ids or any(not isinstance(s, str) for s in ids):
            raise SkillContractError("every part requires source step_ids")
        name = part.get("name")
        if not isinstance(name, str) or not name.strip() or len(name) > 160:
            raise SkillContractError("part name must be 1–160 characters")
        item = {"name": name.strip(), "step_ids": list(ids)}
        for key in ("purpose", "preconditions", "postconditions"):
            value = part.get(key, "" if key == "purpose" else [])
            if key == "purpose":
                if not isinstance(value, str) or len(value) > 2000:
                    raise SkillContractError("part purpose must be concise text")
            elif not isinstance(value, list) or len(value) > 12 or any(not isinstance(v, str) or len(v) > 1000 for v in value):
                raise SkillContractError("part conditions must be concise text lists")
            item[key] = deepcopy(value)
        normalized.append(item)
    source_ids = [s["step_id"] for s in workflow.get("steps", [])]
    flattened = [s for part in normalized for s in part["step_ids"]]
    if not source_ids or len(set(source_ids)) != len(source_ids) or flattened != source_ids:
        raise SkillContractError("parts must cover every source step exactly once in its original order")
    branches = payload.get("branches", [])
    if not isinstance(branches, list) or len(branches) > 32:
        raise SkillContractError("branches must be a list of at most 32 suggestions")
    checked_branches = []
    for branch in branches:
        if not isinstance(branch, dict) or set(branch) - {"after_part", "condition", "description"}:
            raise SkillContractError("branch suggestions cannot contain executable routes or actions")
        index = branch.get("after_part")
        if type(index) is not int or not 1 <= index <= len(normalized):
            raise SkillContractError("branch after_part must reference an existing part (1-based)")
        for key in ("condition", "description"):
            if not isinstance(branch.get(key), str) or not branch[key].strip() or len(branch[key]) > 2000:
                raise SkillContractError("branch condition and description are required")
        checked_branches.append(deepcopy(branch) | {"status": "needs_demonstration", "executable": False})
    return {"parts": normalized, "branches": checked_branches}


class SkillDecomposition:
    def __init__(self, registry: EquipmentSkillRegistry):
        self.registry = registry
        self.root = registry.root.parent / "equipment_skill_splits"

    def source(self, skill_id: str, version: str) -> tuple[dict, dict, str]:
        package = validate_skill_package(self.registry._package_dir(skill_id, version))
        recording = self.registry.get_recording(skill_id, version)
        if canonical_sha256(recording) != package["manifest"]["recording_sha256"]:
            raise SkillContractError("recording hash mismatch")
        revision = canonical_sha256({"workflow": package["workflow"], "annotations": package["annotations"],
                                     "recording": recording, "profile": package["manifest"]["target_profile"]})
        return package, recording, revision

    def _base(self, skill_id, version):
        self.registry._package_dir(skill_id, version)  # Validate identities before filesystem use.
        return self.root / skill_id / version

    def propose(self, skill_id, version, payload, *, model_snapshot, expected_revision=None):
        package, _, revision = self.source(skill_id, version)
        if expected_revision is not None and expected_revision != revision:
            raise SkillContractError("source revision changed during model analysis; generate again")
        partition = validate_partition(package["workflow"], payload)
        proposal_id = uuid4().hex
        for index, part in enumerate(partition["parts"], 1):
            part.update(skill_id=f"{skill_id[:50]}_split_{proposal_id[:12]}_{index:02d}", version="1.0.0")
        proposal = {"schema": "ax4lab.skill_split_proposal.v1", "proposal_id": proposal_id,
                    "source_skill_id": skill_id, "source_version": version, "source_revision": revision,
                    "target_profile": package["manifest"]["target_profile"], "created_at": _now_iso(),
                    "split_recommended": len(partition["parts"]) > 1, "model_snapshot": deepcopy(model_snapshot),
                    **partition}
        base = self._base(skill_id, version)
        _atomic_write_json(base / proposal_id / "proposal.json", proposal)
        _atomic_write_json(base / "latest.json", {"proposal_id": proposal_id})
        return proposal

    def latest(self, skill_id, version):
        base = self._base(skill_id, version)
        if not (base / "latest.json").exists():
            return None
        proposal_id = _safe_identity(_read_json(base / "latest.json")["proposal_id"], "proposal_id")
        proposal = _read_json(base / proposal_id / "proposal.json")
        _, _, revision = self.source(skill_id, version)
        result_path = base / proposal_id / "result.json"
        return {"proposal": proposal, "stale": proposal["source_revision"] != revision,
                "result": _read_json(result_path) if result_path.exists() else None}

    def _child(self, package, recording, proposal, part):
        ids = set(part["step_ids"])
        workflow = deepcopy(package["workflow"])
        workflow.update(skill_id=part["skill_id"], version=part["version"], program_ids=[],
                        steps=[deepcopy(s) for s in workflow["steps"] if s["step_id"] in ids])
        annotations = deepcopy(package["annotations"])
        annotations.update(skill_id=part["skill_id"], version=part["version"], status="review_required")
        by_id = {s["step_id"]: s for s in annotations.get("steps", [])}
        annotations["steps"] = [deepcopy(by_id.get(s["step_id"], {"step_id": s["step_id"], "label": s.get("label", "")}))
                                | {"review_required": True} for s in workflow["steps"]]
        # Full-recording summaries are source context, not claims about this child.
        annotations["source_workflow_summary"] = annotations.pop("workflow_summary", {})
        annotations["workflow_summary"] = {"intent": part["purpose"], "initial_state": part["preconditions"],
                                            "completion_state": part["postconditions"]}
        annotations["step_transitions"] = [s for s in annotations.get("step_transitions", []) if s.get("step_id") in ids]
        annotations["checkpoints"] = []  # Source-level checkpoint scope has not been revalidated.
        provenance = {"proposal_id": proposal["proposal_id"], "skill_id": proposal["source_skill_id"],
                      "version": proposal["source_version"], "source_revision": proposal["source_revision"],
                      "source_step_ids": part["step_ids"], "recording_scope": "full_source_recording"}
        annotations["split_provenance"] = provenance
        annotations["split_model_snapshot"] = deepcopy(proposal["model_snapshot"])
        manifest = {k: deepcopy(package["manifest"][k]) for k in (
            "schema", "target_profile", "platform", "recording_id", "timeline_id", "recording_sha256",
            "recording_evidence", "recording_exceptions", "model_snapshot") if k in package["manifest"]}
        manifest.update(skill_id=part["skill_id"], version=part["version"], name=part["name"],
                        lifecycle="review_required", enabled=True, program_sha256={},
                        workflow_sha256=canonical_sha256(workflow), annotations_sha256=canonical_sha256(annotations),
                        split_provenance=provenance, created_at=proposal["created_at"], updated_at=proposal["created_at"])
        return {"manifest": manifest, "workflow": workflow, "annotations": annotations, "recording": recording}

    def apply(self, skill_id, version, proposal_id, *, confirmed=False):
        if confirmed is not True:
            raise SkillContractError("explicit confirmation is required to create drafts")
        base = self._base(skill_id, version)
        proposal_dir = base / _safe_identity(proposal_id, "proposal_id")
        if not (proposal_dir / "proposal.json").is_file():
            raise SkillContractError("split proposal not found")
        with (base / ".apply.lock").open("a") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            result_path = proposal_dir / "result.json"
            if result_path.exists():
                return _read_json(result_path)  # Idempotent confirmation; never recreate edited/deleted children.
            proposal = _read_json(proposal_dir / "proposal.json")
            package, recording, revision = self.source(skill_id, version)
            if revision != proposal["source_revision"]:
                raise SkillContractError("source revision changed; generate a new proposal")
            if not proposal["split_recommended"]:
                raise SkillContractError("single-purpose workflow does not need splitting")
            # Revalidate persisted model boundaries; metadata is not execution authority.
            validate_partition(package["workflow"], {
                "parts": [{k: p[k] for k in ("name", "step_ids", "purpose", "preconditions", "postconditions")} for p in proposal["parts"]],
                "branches": [{k: b[k] for k in ("after_part", "condition", "description")} for b in proposal["branches"]],
            })
            children = [self._child(package, recording, proposal, part) for part in proposal["parts"]]
            destinations = [self.registry._package_dir(c["manifest"]["skill_id"], c["manifest"]["version"]) for c in children]
            existing = set()
            for dest, child in zip(destinations, children):
                if dest.exists():
                    # Resume a process-interrupted publication only when every file matches.
                    try:
                        matches = all(_read_json(dest / f"{name}.json") == value for name, value in child.items())
                    except (SkillContractError, OSError):
                        matches = False
                    if not matches:
                        raise SkillContractError("child destination already exists or conflicts")
                    existing.add(dest)
            published = []
            with tempfile.TemporaryDirectory(prefix=".split-stage-", dir=base) as temporary:
                staging = Path(temporary)
                for i, child in enumerate(children):
                    for name, value in child.items():
                        _atomic_write_json(staging / str(i) / f"{name}.json", value)
                    validate_skill_package(staging / str(i))
                try:
                    if self.source(skill_id, version)[2] != revision:
                        raise SkillContractError("source revision changed before publication")
                    for i, dest in enumerate(destinations):
                        if dest in existing:
                            continue
                        dest.parent.mkdir(parents=True, exist_ok=True)
                        (staging / str(i)).rename(dest)
                        published.append(dest)
                    result = {"proposal_id": proposal_id, "children": [
                        {"skill_id": p["skill_id"], "version": p["version"], "name": p["name"]} for p in proposal["parts"]],
                        "composition": {"schema": "ax4lab.skill_composition_draft.v1", "executable": False,
                                        "target_profile": proposal["target_profile"], "parts": proposal["parts"],
                                        "order": "recorded_sequence", "branches": proposal["branches"]}}
                    if self.source(skill_id, version)[2] != revision:
                        raise SkillContractError("source revision changed during publication")
                    _atomic_write_json(result_path, result)
                except Exception:
                    for dest in published:
                        shutil.rmtree(dest)  # Only exact new paths owned by this transaction.
                    raise
            return result
