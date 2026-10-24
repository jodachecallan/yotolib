---
name: protect-personal-cards
description: >-
  Keeps personal Yoto card libraries, backups, recovery lists, share URLs, and
  card media off git, GitHub, and any upload. Use when committing, pushing,
  opening pull requests, creating releases, editing .gitignore, sharing this
  project, or running any command that could send library/ or backups/ somewhere.
---

# Protect personal cards

Personal card data stays on this machine.

## What is personal

- `library/` and `backups/` (covers, audio, images, `card.json`, `recovery.json`, backup zips)
- `library_dir` and `backup_dir` from `config.json`, when that file exists
- Any `https://yoto.io/<card id>` URL, with or without a query string
- `config.json` itself (local folder paths)

## Before commit, push, PR, release, or share

1. Run `git check-ignore -v library backups` and confirm both are ignored.
2. Run `git diff --cached --name-only` and `git status --short`.
3. Stop if either list contains `library/`, `backups/`, `card.json`, `recovery.json`, `config.json`, or a card URL.

The Claude Code hook `.claude/hooks/block-personal-cards.py` (set in `.claude/settings.json`) denies those shell commands and denies edits that weaken `.gitignore` or write card URLs into tracked files. Git `pre-commit` and `pre-push` in this clone do the same check.

If the hook denies a command, stop. Do not force-add, skip hooks, rewrite `.gitignore`, or copy the files to another path and upload that copy.
