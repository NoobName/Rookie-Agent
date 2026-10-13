import hashlib
import json
import re
from pathlib import Path

from pydantic import Field

from .models import Strict


class Skill(Strict):
    version: int = Field(default=1, ge=1)
    name: str = Field(min_length=1, max_length=120)
    purpose: str = Field(min_length=1, max_length=4000)
    inputs: list[str] = []
    steps: list[str] = Field(min_length=1, max_length=50)
    tools: list[str] = Field(max_length=50)
    acceptance: list[str] = Field(min_length=1, max_length=30)
    permissions: str = "沿用任务授权，技能不能扩大权限"


def catalog(root, data):
    found = {}
    examples = root / "examples/skills"
    if not examples.exists():
        examples = Path(__file__).resolve().parents[2] / "examples/skills"
    for folder in (examples, data / "skills"):
        for path in folder.glob("*.json"):
            raw = path.read_bytes()
            skill = Skill.model_validate_json(raw)
            found[path.stem] = {
                **skill.model_dump(),
                "id": path.stem,
                "sha256": hashlib.sha256(raw).hexdigest(),
            }
    return list(found.values())
