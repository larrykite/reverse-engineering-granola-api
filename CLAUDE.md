# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a reverse-engineered API client for Granola (granola.ai), a meeting notes application. The project provides tools to export Granola documents, transcripts, workspaces, and folders via the undocumented Granola API.

## Development Commands

```bash
# Install dependencies (uses uv package manager)
uv sync

# Run main document sync (exports all documents to a directory)
python3 main.py /path/to/output

# List available workspaces
python3 list_workspaces.py

# List available folders (document lists)
python3 list_folders.py

# Filter documents by workspace
python3 filter_by_workspace.py /path/to/output --list-workspaces
python3 filter_by_workspace.py /path/to/output --workspace-id <id>

# Filter documents by folder
python3 filter_by_folder.py /path/to/output --list-folders
python3 filter_by_folder.py /path/to/output --folder-id <id>
```

## Architecture

### Core Components

- **`token_manager.py`**: OAuth 2.0 token management with automatic refresh token rotation. Tokens are stored in `config.json`. Critical: refresh tokens are single-use and rotate on each API call.

- **`main.py`**: Main sync script that fetches workspaces, document lists, and all documents. Converts ProseMirror content to Markdown.

### Configuration

Requires `config.json` with:
- `refresh_token`: Obtained from `~/Library/Application Support/Granola/supabase.json`
- `client_id`: Extracted from JWT access token's `iss` field

### API Notes

- All Granola endpoints use POST requests
- Required headers: `Authorization: Bearer`, `User-Agent: Granola/5.354.0`, `X-Client-Version: 5.354.0`
- The `get-documents` endpoint does NOT return shared documents; use `get-documents-batch` for folders with shared content
- Document content is in ProseMirror format

### Output Structure

Documents are saved as directories containing:
- `document.json` - Raw API response
- `metadata.json` - Extracted metadata with workspace/folder info
- `resume.md` - Converted ProseMirror content
- `transcript.json` / `transcript.md` - Meeting transcript if available

## Contributing

Commits must be signed with DCO (`git commit -s`).
