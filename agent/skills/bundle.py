"""Pack and unpack skill directories as tar.gz bundles."""

from __future__ import annotations

import shutil
import tarfile
import tempfile
from pathlib import Path

from agent.skills.discovery import discover_skills


def create_skills_bundle(*, skills_root: Path, output_path: Path) -> Path:
    """Create ``output_path`` tar.gz containing every ``skills_root/*/`` tree with ``SKILL.md``."""
    if not skills_root.is_dir():
        raise FileNotFoundError(f"Skills directory not found: {skills_root}")
    names = discover_skills(skills_root)
    if not names:
        raise ValueError(f"No skills with SKILL.md under {skills_root}")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(output_path, "w:gz") as tar:
        for name in sorted(names):
            tar.add(skills_root / name, arcname=name)
    return output_path


def extract_skills_bundle(*, bundle_path: Path, target_dir: Path) -> Path:
    """Extract bundle into ``target_dir`` (replaces existing content)."""
    if not bundle_path.is_file():
        raise FileNotFoundError(f"Skills bundle not found: {bundle_path}")

    if target_dir.exists():
        shutil.rmtree(target_dir)
    target_dir.mkdir(parents=True, exist_ok=True)

    with tarfile.open(bundle_path, "r:gz") as tar:
        _safe_extract(tar, target_dir)
    return target_dir


def _safe_extract(tar: tarfile.TarFile, target_dir: Path) -> None:
    """Extract tar members only under ``target_dir`` (no path traversal)."""
    target = target_dir.resolve()
    for member in tar.getmembers():
        dest = (target / member.name).resolve()
        if not str(dest).startswith(str(target)):
            raise tarfile.TarError(f"Unsafe path in bundle: {member.name}")
    if hasattr(tarfile, "data_filter"):
        tar.extractall(path=target, filter="data")
    else:
        tar.extractall(path=target)


def write_temp_bundle(*, skills_root: Path) -> Path:
    """Create a temporary tar.gz bundle and return its path."""
    tmp = Path(tempfile.mkstemp(suffix=".tar.gz", prefix="datasyn-skills-")[1])
    return create_skills_bundle(skills_root=skills_root, output_path=tmp)
