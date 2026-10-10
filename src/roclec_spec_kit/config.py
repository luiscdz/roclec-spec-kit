"""Project-local configuration for a Roclec installation."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
import tomllib

NAME_RE = re.compile(r"^[a-z][a-z0-9-]*$")
CONFIG_PATH = Path(".roclec/project.toml")
LINK_PATH = Path(".roclec/link.toml")


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class Component:
    name: str
    repo: Path
    user_facing: bool = False


@dataclass(frozen=True)
class Project:
    root: Path
    name: str
    components: dict[str, Component]

    @property
    def specs(self) -> Path:
        return self.root / "specs"

    @property
    def releases(self) -> Path:
        return self.root / "roadmap/releases"


def find_config(start: Path) -> Path:
    current = start.resolve()
    if current.is_file():
        current = current.parent
    for directory in (current, *current.parents):
        candidate = directory / CONFIG_PATH
        if candidate.is_file():
            return candidate
        link = directory / LINK_PATH
        if link.is_file():
            try:
                data = tomllib.loads(link.read_text(encoding="utf-8"))
            except (OSError, tomllib.TOMLDecodeError) as exc:
                raise ConfigError(f"Cannot read {link}: {exc}") from exc
            target = data.get("project_root")
            if data.get("schema") != 1 or not isinstance(target, str) or not target or Path(target).is_absolute():
                raise ConfigError(f"Invalid {link}")
            linked_config = (directory / target / CONFIG_PATH).resolve()
            if not linked_config.is_file():
                raise ConfigError(f"Broken Roclec link: {linked_config}")
            return linked_config
    raise ConfigError(f"No {CONFIG_PATH} found from {start}")


def load_project(start: Path) -> Project:
    config_path = find_config(start)
    root = config_path.parent.parent
    try:
        data = tomllib.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ConfigError(f"Cannot read {config_path}: {exc}") from exc
    if data.get("schema") != 1:
        raise ConfigError("project.toml needs schema = 1")
    name = data.get("name")
    if not isinstance(name, str) or not name.strip():
        raise ConfigError("project.toml needs a nonempty name")
    raw_components = data.get("components")
    if not isinstance(raw_components, dict) or not raw_components:
        raise ConfigError("project.toml needs at least one [components.<name>] table")
    components: dict[str, Component] = {}
    for key, value in raw_components.items():
        if not NAME_RE.fullmatch(key) or not isinstance(value, dict):
            raise ConfigError(f"Invalid component name or table: {key}")
        repo = value.get("repo")
        if not isinstance(repo, str) or not repo or Path(repo).is_absolute():
            raise ConfigError(f"{key}.repo must be a relative path")
        user_facing = value.get("user_facing", False)
        if not isinstance(user_facing, bool):
            raise ConfigError(f"{key}.user_facing must be true or false")
        components[key] = Component(key, (root / repo).resolve(), user_facing)
    return Project(root, name, components)


def render_config(name: str, components: dict[str, tuple[str, bool]]) -> str:
    lines = ["# Roclec project profile. Paths are relative to this project root.", "schema = 1", f"name = {json.dumps(name)}", ""]
    for component, (repo, user_facing) in components.items():
        lines += [f"[components.{component}]", f"repo = {json.dumps(repo)}", f"user_facing = {str(user_facing).lower()}", ""]
    return "\n".join(lines)
