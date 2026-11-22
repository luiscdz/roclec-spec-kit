<!-- managed by roclec-spec-kit -->
# Recording an agent session

Use this when a stage with `session_evidence = "required"` (or optional, when the user wants the session kept) closes. Roclec stores the transcript without interpreting it: `roclec evidence record --kind agent-session --file META.json --transcript EXPORT`. Never fabricate a transcript or its metadata; if you cannot obtain the export, ask the user for it.

## Get the session id and the export

These locations are host behaviour that may change. Ask the user to confirm the file before importing it.

- **Claude Code.** Session transcripts are JSONL files under `~/.claude/projects/<project-folder>/<session-id>.jsonl`. The session id is shown by `/status`.
- **Codex.** Rollout JSONL files live under `~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl`; the session id is part of the file name and of its first record.

A delegated role reports its own host and session id in its output; the coordinator maps it to the export of that session.

## Fill META.json

Do not declare `kind`; the command sets it.

```json
{
  "model_schema": 2,
  "host": "claude-code",
  "host_session_id": "id from the host",
  "actor": "who ran the session",
  "role": "specifier|implementer|reviewer|coordinator|agent role declared in flow.toml",
  "model": "model that ran it",
  "started_at": "2026-01-01T10:00:00Z",
  "ended_at": "2026-01-01T11:00:00Z",
  "stage": "flow stage name",
  "change_id": "CHG-001",
  "component": "NAME"
}
```

- Times are UTC `YYYY-MM-DDTHH:MM:SSZ`; `ended_at` is not before `started_at`. Take them from the export, not from memory.
- Scope by stage: `change_id` for every stage except foundation and release, plus `component` for design, implement, verify, review and integrate (optional for define, approve and plan). A define session may name a CHG id not imported yet. Foundation uses `subject` (the reference or ADR id) instead. Release uses `release` `{"component": "NAME", "version": "vX.Y.0"}`.
- Cite the resulting EVD id with `--session EVD-...` (repeatable) on the closing record: `change approve|cancel|start`, `foundation agree`, `reject`, `checkpoint`, `fut decide` and `run verify`. An independent review cites the reviewer's session as its `context` when the review stage requires sessions.

## Privacy

Transcripts contain code, paths, names and possibly personal data. Redaction covers only the profile's configured `secret_env` values and `redact_patterns`; it does not find anything else. Before versioning, review `[sessions] storage` in the profile: `versioned-redacted` (default), `local` (nothing versioned) or `versioned-raw` (may contain secrets). Choose `local` when in doubt. A transcript over `quota_bytes` is rejected, never truncated.
