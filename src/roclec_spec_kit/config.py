"""Project-local configuration for a Roclec installation."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
import subprocess
import tomllib

NAME_RE = re.compile(r"^[a-z][a-z0-9-]*$")
CONFIG_PATH = Path(".roclec/project.toml")
LINK_PATH = Path(".roclec/link.toml")
DEFAULT_LOG_QUOTA = 16 * 1024 * 1024
DEFAULT_MAX_LOG_BYTES = 0
FINDING_SEVERITIES = ("info", "minor", "major", "blocker")
# Agent-session transcripts (M-34): where the imported copy lives and the per-session size limit.
SESSION_STORAGES = ("versioned-redacted", "local", "versioned-raw")
SESSION_DEFAULTS = {"storage": "versioned-redacted", "quota_bytes": 16 * 1024 * 1024}
ENV_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class Component:
    name: str
    repo: Path
    user_facing: bool = False
    product: dict[str, str] | None = None


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
        product = value.get("product")
        if product is not None:
            if not user_facing or not isinstance(product, dict) or set(product) - {"core", "source", "output", "design"}:
                raise ConfigError(f"{key}.product needs a user-facing component and supported paths")
            defaults = {"core": "product/core.md", "source": f"product/{key}.md", "output": f"components/{key}/PRODUCT.md", "design": f"components/{key}/DESIGN.md"}
            product = {**defaults, **product}
            for label, relative in product.items():
                if not isinstance(relative, str) or not relative or Path(relative).is_absolute() or not (root / relative).resolve().is_relative_to(root):
                    raise ConfigError(f"{key}.product.{label} must stay within project root")
            if len({(root / p).resolve() for p in product.values()}) != 4:
                raise ConfigError(f"{key}.product sources and outputs must be distinct")
        components[key] = Component(key, (root / repo).resolve(), user_facing, product)
    outputs = [(root / c.product["output"]).resolve() for c in components.values() if c.product]
    inputs = {(root / c.product[k]).resolve() for c in components.values() if c.product for k in ("core", "source", "design")}
    if len(outputs) != len(set(outputs)) or inputs.intersection(outputs):
        raise ConfigError("product outputs must be unique and cannot overwrite sources/design")
    return Project(root, name, components)


def render_config(name: str, components: dict[str, tuple[str, bool]]) -> str:
    lines = ["# Roclec project profile. Paths are relative to this project root.", "schema = 1", f"name = {json.dumps(name)}", ""]
    for component, (repo, user_facing) in components.items():
        lines += [f"[components.{component}]", f"repo = {json.dumps(repo)}", f"user_facing = {str(user_facing).lower()}", ""]
    return "\n".join(lines)


# The public CLI uses this profile. The schema-1 functions above remain available
# only to characterize the pre-redesign implementation during C1/C2 development.
@dataclass(frozen=True)
class Profile:
    root: Path
    data: dict

    @property
    def components(self):
        return self.data["components"]

    @property
    def review_enabled(self) -> bool:
        return self.data.get("review", {}).get("enabled", True)

    @property
    def material_severity(self) -> str:
        return self.data.get("review", {}).get("material_severity", "major")

    def repo(self, component: str) -> Path:
        from .model import need
        need(component in self.components, "INVALID_REFERENCE", "Unknown component", entity=component)
        return (self.root / self.components[component]["repo"]).resolve()

    @property
    def sessions(self) -> dict:
        """Agent-session storage policy and per-session quota, with defaults."""
        return {**SESSION_DEFAULTS, **self.data.get("sessions", {})}

    @property
    def adr(self) -> dict:
        """ADR location and structure, with the shipped template's defaults (D13)."""
        return {**ADR_DEFAULTS, **self.data.get("adr", {})}

    def agent_model(self, role: str, host: str) -> str | None:
        """Model pinned for a role's host binding, or None to inherit the host session's model."""
        return self.data.get("agents", {}).get(role, {}).get(host)


def validate_agents(agents):
    """Optional ``[agents.<role>]`` tables: one model name per host, passed to the host uninterpreted (D10)."""
    from .agents import HOSTS, subagent_roles
    from .model import need, text
    roles = subagent_roles()
    need(isinstance(agents, dict), "INVALID_INPUT", "agents must be a table of roles", exit_code=2,
         remediation="Use [agents.<role>] tables, or remove agents to inherit each host session's model.")
    for role, hosts in agents.items():
        need(role in roles, "INVALID_INPUT", "Unknown agent role", exit_code=2, entity=role,
             expected=list(roles), actual=role,
             remediation=f"Use one of {', '.join(roles)}; the coordinator runs in the user's session and uses its model.")
        need(isinstance(hosts, dict), "INVALID_INPUT", "An agent role must be a table of hosts", exit_code=2, entity=role,
             remediation=f"Write [agents.{role}] with host = \"model\" entries.")
        for host, model in hosts.items():
            need(host in HOSTS, "INVALID_INPUT", "Unsupported agent host", exit_code=2, entity=f"{role}.{host}",
                 expected=list(HOSTS), actual=host, remediation=f"Use one of {', '.join(HOSTS)} under [agents.{role}].")
            need(text(model) and model == model.strip() and not any(ord(c) < 32 or c in "\"'\\" for c in model),
                 "INVALID_INPUT", "Agent model must be a single-line name", exit_code=2, entity=f"{role}.{host}",
                 remediation="Write the host's model name, or remove the entry to inherit the session's model.")


ADR_DEFAULTS = {
    "path": "docs/adr",
    "required_sections": ["Context and problem", "Decision drivers", "Considered options", "Decision",
                          "Consequences", "Compliance verification", "Relations"],
    "options_section": "Considered options",
}


def validate_adr(adr):
    """Optional ``[adr]`` table: ADR folder, required ``##`` sections and the section holding ``###`` options."""
    from .model import fields, need, text
    need(isinstance(adr, dict), "INVALID_INPUT", "adr must be a table", exit_code=2,
         remediation="Write [adr] with path, required_sections or options_section, or remove it to use the defaults.")
    fields(adr, (), tuple(ADR_DEFAULTS))
    merged = {**ADR_DEFAULTS, **adr}
    path = merged["path"]
    need(text(path) and not Path(path).is_absolute() and ".." not in Path(path).parts and "\\" not in path,
         "INVALID_PATH", "adr.path must be a relative folder inside the project", exit_code=2, actual=path)
    sections = merged["required_sections"]
    need(isinstance(sections, list) and bool(sections) and all(text(s) and s == s.strip() and "\n" not in s for s in sections)
         and len({s.casefold() for s in sections}) == len(sections),
         "INVALID_INPUT", "adr.required_sections must list distinct single-line section titles", exit_code=2)
    need(text(merged["options_section"]) and merged["options_section"].casefold() in {s.casefold() for s in sections},
         "INVALID_INPUT", "adr.options_section must be one of adr.required_sections", exit_code=2,
         remediation="Name the required section whose ### subsections are the considered options.")


def validate_ref(ref, prefix):
    from .model import need, text
    need(text(ref) and ref.startswith(prefix) and "\x00" not in ref,
         "INVALID_INPUT", f"Expected a full Git reference starting with {prefix}", exit_code=2, actual=ref)
    result = subprocess.run(["git", "check-ref-format", ref], capture_output=True, timeout=10)
    need(result.returncode == 0, "INVALID_INPUT", "Invalid Git reference", exit_code=2, actual=ref)


def validate_profile(root: Path, data: dict) -> Profile:
    from .model import fields, need, text
    need(isinstance(data, dict) and type(data.get("schema")) is int and data["schema"] == 3, "UNSUPPORTED_SCHEMA",
         "The native CLI requires project.toml schema = 3",
         exit_code=2, expected=3, actual=data.get("schema") if isinstance(data, dict) else None,
         remediation="Use the previous wheel for an existing profile, or initialize profile 3 in a separate project.")
    fields(data, ("schema", "name", "components", "trunk_ref"),
           ("log_quota_bytes", "max_log_bytes", "secret_env", "redact_patterns", "agents", "adr", "review", "sessions"))
    validate_ref(data["trunk_ref"], "refs/heads/")
    if "agents" in data:
        validate_agents(data["agents"])
    if "adr" in data:
        validate_adr(data["adr"])
    review = data.get("review", {})
    fields(review, (), ("enabled", "material_severity"))
    need(type(review.get("enabled", True)) is bool, "INVALID_INPUT", "review.enabled must be boolean", exit_code=2)
    need(review.get("material_severity", "major") in FINDING_SEVERITIES,
         "INVALID_INPUT", "Unknown review.material_severity", exit_code=2,
         expected=list(FINDING_SEVERITIES), actual=review.get("material_severity"))
    sessions = data.get("sessions", {})
    need(isinstance(sessions, dict), "INVALID_INPUT", "sessions must be a table", exit_code=2,
         remediation="Write [sessions] with storage or quota_bytes, or remove it to use the defaults.")
    fields(sessions, (), tuple(SESSION_DEFAULTS))
    need(sessions.get("storage", SESSION_DEFAULTS["storage"]) in SESSION_STORAGES, "INVALID_INPUT",
         "Unknown sessions.storage", exit_code=2, expected=list(SESSION_STORAGES), actual=sessions.get("storage"),
         remediation="Use one of: " + ", ".join(SESSION_STORAGES) + ".")
    session_quota = sessions.get("quota_bytes", SESSION_DEFAULTS["quota_bytes"])
    need(type(session_quota) is int and session_quota > 0, "INVALID_INPUT", "sessions.quota_bytes must be a positive integer",
         exit_code=2, actual=session_quota, remediation="Set quota_bytes to a positive number of bytes, or remove it.")
    quota = data.get("log_quota_bytes", DEFAULT_LOG_QUOTA)
    excerpt = data.get("max_log_bytes", DEFAULT_MAX_LOG_BYTES)
    need(type(quota) is int and quota > 0 and type(excerpt) is int and 0 <= excerpt <= min(quota, 1024 * 1024),
         "INVALID_INPUT", "Require a positive log quota and an excerpt of at most 1 MiB within that quota", exit_code=2)
    def env_names(value):
        return isinstance(value, list) and all(isinstance(name, str) and ENV_NAME.fullmatch(name) for name in value)
    need(env_names(data.get("secret_env", [])), "INVALID_INPUT", "secret_env must list variable names", exit_code=2)
    patterns = data.get("redact_patterns", [])
    need(isinstance(patterns, list) and all(text(pattern) for pattern in patterns),
         "INVALID_INPUT", "redact_patterns must list regular expressions", exit_code=2)
    for pattern in patterns:
        try:
            re.compile(pattern)
        except re.error as exc:
            from .model import ModelError
            raise ModelError("INVALID_INPUT", "Invalid log redaction pattern", exit_code=2) from exc
    need(text(data["name"]) and isinstance(data["components"], dict) and bool(data["components"]),
         "INVALID_INPUT", "A project needs a name and configured components", exit_code=2)
    for name, entry in data["components"].items():
        need(NAME_RE.fullmatch(name) is not None, "INVALID_INPUT", "Invalid component name", exit_code=2)
        fields(entry, ("repo", "user_facing", "inputs", "generated", "verification", "target_ref"), ("excluded",))
        validate_ref(entry["target_ref"], "refs/remotes/")
        need(len(entry["target_ref"].split("/")) >= 4, "INVALID_INPUT", "Remote tracking ref requires remote and branch", exit_code=2)
        relative = entry["repo"]
        need(text(relative) and not Path(relative).is_absolute() and "\\" not in relative,
             "INVALID_PATH", "Component repo must be a relative configured path", exit_code=2)
        repo = (root / relative).resolve()
        need(repo == root.resolve() or repo.is_dir(), "INVALID_REFERENCE", "Configured code repo is missing", path=relative)
        need(type(entry["user_facing"]) is bool, "INVALID_INPUT", "user_facing must be boolean", exit_code=2)
        for key in ("inputs", "generated", "excluded"):
            patterns = entry.get(key, [])
            need(isinstance(patterns, list) and all(text(p) and not p.startswith("/") and
                 ".." not in Path(p).parts and "\\" not in p for p in patterns),
                 "INVALID_PATH", f"{key} must be relative path patterns", exit_code=2)
            need(len(patterns) == len(set(patterns)), "INVALID_INPUT", "Duplicate path pattern", exit_code=2)
        need(bool(entry["inputs"]) and not set(entry["inputs"]) & set(entry["generated"]),
             "INVALID_INPUT", "Declare nonempty inputs distinct from generated paths", exit_code=2)
        checks = entry["verification"]
        need(isinstance(checks, list), "INVALID_INPUT", "verification must be a list", exit_code=2)
        check_ids = []
        for check in checks:
            fields(check, ("id", "argv", "cwd", "timeout_seconds"), ("acceptance_ids", "env"))
            need(env_names(check.get("env", [])), "INVALID_INPUT", "Check env must list variable names", exit_code=2)
            from .model import identifier, strings
            for ac in strings(check.get("acceptance_ids", [])):
                identifier(ac, "AC")
            need(text(check["id"]) and isinstance(check["argv"], list) and bool(check["argv"])
                 and all(text(arg) and "\x00" not in arg for arg in check["argv"]), "INVALID_INPUT", "Checks need id and argv", exit_code=2)
            cwd = check["cwd"]
            need(text(cwd) and not Path(cwd).is_absolute() and ".." not in Path(cwd).parts and "\\" not in cwd
                 and (repo / cwd).resolve().is_relative_to(repo), "INVALID_PATH", "Check cwd must stay in repo", exit_code=2)
            need(type(check["timeout_seconds"]) is int and check["timeout_seconds"] > 0,
                 "INVALID_INPUT", "Check timeout must be a positive integer", exit_code=2)
            check_ids.append(check["id"])
        need(len(check_ids) == len(set(check_ids)), "ID_COLLISION", "Duplicate verification check ID")
    return Profile(root.resolve(), data)


def load_profile(start: Path) -> Profile:
    from .model import ModelError, local_path
    config_path = find_config(start)
    root = config_path.parent.parent.resolve()
    local_path(root, ".roclec/project.toml")
    try:
        data = tomllib.loads(config_path.read_text(encoding="utf-8"))
    except (tomllib.TOMLDecodeError, UnicodeError) as exc:
        raise ModelError("INVALID_INPUT", f"Invalid project profile: {exc}", exit_code=2, path=config_path) from exc
    return validate_profile(root, data)
