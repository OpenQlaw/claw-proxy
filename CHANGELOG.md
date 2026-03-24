# Changelog

All notable changes to claw-proxy are documented here.  
Format: [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).  
Versioning: [SemVer](https://semver.org/).

## [Unreleased]

## [0.1.0] - 2026-03-23

### Added
- Quota-aware OpenAI-compatible HTTP gateway (`POST /v1/chat/completions`)
- Three routing backends: GitHub Copilot API, Claude Code CLI, LM Studio passthrough
- Security-first routing: messages containing credential keywords force local backend
- `claw-proxy` CLI entry point (`uvicorn` wrapper on `127.0.0.1:8020`)
- Sanitizer with 8 pattern types: GitHub PAT/app/oauth, Anthropic key, OpenAI key, AWS access key, base64 generic, KV secret pairs
- Quota state file at `~/.config/claw-proxy/quota-state.json` with auto-reset logic
- `GET /health`, `GET /quota`, `GET /v1/models` utility endpoints
- AGPL-3.0 license
