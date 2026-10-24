#!/usr/bin/env python3
"""Block commits and uploads of personal Yoto card data.

Claude Code PreToolUse hook (stdin JSON) and git pre-commit / pre-push hook.
Personal data is the card library and backups, including custom folders
from config.json, plus Yoto card URLs. Local reads stay allowed.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path

SHARE_URL = re.compile(r"https?://yoto\.io/[A-Za-z0-9]{4,}", re.IGNORECASE)
PERSONAL_FILENAMES = {"card.json", "recovery.json"}
SHELLS = {"bash", "sh", "zsh", "dash", "busybox"}
TRANSFER = {"cp", "mv", "install", "rsync", "scp", "rclone"}
CLOUD = {"aws", "gsutil", "az", "azcopy", "lftp", "ftp", "nc", "ncat"}
READ_TOOLS = {"read", "grep", "glob", "webfetch", "websearch", "toolsearch"}

USER_MESSAGE = (
    "Blocked so personal Yoto cards stay on this machine. "
    "library/, backups/, card files, and card share URLs are not uploaded."
)


def deny_payload(reason: str) -> str:
    return json.dumps(
        {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": USER_MESSAGE + " " + reason,
            }
        }
    )


def emit_claude(reason: str | None) -> int:
    # Allow is silent so the normal permission flow still applies.
    if reason:
        sys.stdout.write(deny_payload(reason))
    return 0


def git(repo: Path, args: list[str], check: bool = False) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        check=check,
    )


def repo_root(start: Path) -> Path | None:
    proc = git(start if start.is_dir() else start.parent, ["rev-parse", "--show-toplevel"])
    if proc.returncode != 0:
        return None
    return Path(proc.stdout.strip())


def personal_roots(repo: Path | None, cwd: Path) -> list[Path]:
    bases = [cwd]
    if repo is not None:
        bases.insert(0, repo)
    roots: list[Path] = []
    seen: set[Path] = set()
    for base in bases:
        for name in ("library", "backups"):
            path = (base / name).resolve()
            if path not in seen:
                seen.add(path)
                roots.append(path)
    config_places = []
    if repo is not None:
        config_places.append(repo / "config.json")
    config_places.append(cwd / "config.json")
    for config in config_places:
        if not config.is_file():
            continue
        try:
            data = json.loads(config.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(data, dict):
            continue
        for key in ("library_dir", "backup_dir"):
            raw = data.get(key)
            if not isinstance(raw, str) or not raw.strip():
                continue
            path = Path(raw).expanduser()
            if not path.is_absolute():
                path = config.parent / path
            path = path.resolve()
            if path not in seen:
                seen.add(path)
                roots.append(path)
    return roots


def inside(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except (OSError, ValueError):
        return False


def is_personal_path(token: str, cwd: Path, roots: list[Path], repo: Path | None) -> bool:
    text = token.strip().strip("\"'")
    if not text or text.startswith("-"):
        return False
    name = Path(text.rstrip("/")).name
    if name in PERSONAL_FILENAMES or name == "config.json":
        # card.json, recovery.json, and config.json are personal wherever they sit.
        return True
    normalized = text.replace("\\", "/").lstrip("./")
    if normalized in {"library", "backups"} or normalized.startswith(("library/", "backups/")):
        return True
    candidate = Path(text)
    if not candidate.is_absolute():
        candidate = cwd / candidate
    if any(inside(candidate, root) for root in roots):
        return True
    if repo is not None:
        try:
            rel = candidate.resolve().relative_to(repo.resolve()).as_posix()
        except (OSError, ValueError):
            rel = ""
        if rel in {"library", "backups"} or rel.startswith(("library/", "backups/")):
            return True
        if Path(rel).name in PERSONAL_FILENAMES:
            return True
    return False


def gitignore_protects(text: str) -> bool:
    covered = set()
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or line.startswith("!"):
            continue
        for name in ("library", "backups"):
            if line.rstrip("/") in {name, name + "/**"} or line.startswith(name + "/"):
                covered.add(name)
        if line in {"config.json", "/config.json", "**/config.json"}:
            covered.add("config.json")
    return {"library", "backups", "config.json"} <= covered


def ignore_rules_active(repo: Path) -> bool:
    for rel in ("library", "backups", "config.json"):
        proc = git(repo, ["check-ignore", "-q", rel])
        if proc.returncode != 0:
            return False
    return True


def unwrap_shell(command: str) -> str:
    try:
        argv = shlex.split(command, posix=True)
    except ValueError:
        return command
    if not argv:
        return command
    if Path(argv[0]).name not in SHELLS:
        return command
    for index, arg in enumerate(argv):
        if arg == "-c" or (arg.startswith("-") and not arg.startswith("--") and "c" in arg[1:]):
            if index + 1 < len(argv):
                return argv[index + 1]
    return command


def split_commands(command: str) -> list[str]:
    parts: list[str] = []
    buf: list[str] = []
    single = False
    double = False
    index = 0
    while index < len(command):
        char = command[index]
        if char == "'" and not double:
            single = not single
            buf.append(char)
        elif char == '"' and not single:
            double = not double
            buf.append(char)
        elif not single and not double and command.startswith("&&", index):
            parts.append("".join(buf))
            buf = []
            index += 2
            continue
        elif not single and not double and command.startswith("||", index):
            parts.append("".join(buf))
            buf = []
            index += 2
            continue
        elif not single and not double and char in ";|\n":
            parts.append("".join(buf))
            buf = []
        else:
            buf.append(char)
        index += 1
    if buf:
        parts.append("".join(buf))
    return [part.strip() for part in parts if part.strip()]


def parse_git(argv: list[str], cwd: Path) -> tuple[str, list[str], Path] | None:
    if not argv or Path(argv[0]).name not in {"git", "git.exe"}:
        return None
    work = cwd
    index = 1
    while index < len(argv):
        arg = argv[index]
        if arg == "-C" and index + 1 < len(argv):
            raw = Path(argv[index + 1])
            work = raw if raw.is_absolute() else cwd / raw
            index += 2
            continue
        if arg in {"-c", "--git-dir", "--work-tree"} and index + 1 < len(argv):
            index += 2
            continue
        if arg.startswith("-"):
            index += 1
            continue
        return arg, argv[index + 1 :], work
    return None


def non_options(argv: list[str]) -> list[str]:
    values: list[str] = []
    index = 1
    while index < len(argv):
        arg = argv[index]
        if arg == "--":
            values.extend(argv[index + 1 :])
            break
        if arg.startswith("-"):
            index += 1
            continue
        values.append(arg)
        index += 1
    return values


def is_remote(token: str) -> bool:
    if "://" in token:
        return True
    if re.match(r"^[^/\s]+:", token):
        return True
    return False


def added_share_urls(diff: str) -> bool:
    for line in diff.splitlines():
        if line.startswith("+") and not line.startswith("+++") and SHARE_URL.search(line):
            return True
    return False


def personal_status_paths(name_status: str, repo: Path, roots: list[Path]) -> list[str]:
    found: list[str] = []
    for line in name_status.splitlines():
        if not line.strip():
            continue
        parts = line.split("\t")
        status = parts[0]
        if status.startswith("D"):
            continue
        path = parts[-1]
        if is_personal_path(path, repo, roots, repo):
            found.append(path)
    return found


def staged_problems(repo: Path, roots: list[Path]) -> str | None:
    status = git(repo, ["diff", "--cached", "--name-status"])
    if status.returncode != 0:
        return "Could not inspect the index, so the commit was blocked."
    paths = personal_status_paths(status.stdout, repo, roots)
    if paths:
        return "The index includes personal card files (" + ", ".join(paths) + ")."
    diff = git(repo, ["diff", "--cached", "--unified=0"])
    if diff.returncode != 0:
        return "Could not inspect the staged diff, so the commit was blocked."
    if added_share_urls(diff.stdout):
        return "The staged diff adds a Yoto card URL."
    return None


def tree_problems(repo: Path, rev: str, roots: list[Path]) -> str | None:
    listed = git(repo, ["ls-tree", "-r", "--name-only", rev])
    if listed.returncode != 0:
        return f"Could not inspect {rev}, so the push was blocked."
    paths = [
        line
        for line in listed.stdout.splitlines()
        if line.strip() and is_personal_path(line.strip(), repo, roots, repo)
    ]
    if paths:
        return "The commit being pushed still contains personal card files (" + ", ".join(paths) + ")."
    return None


def range_problems(repo: Path, rev_range: str, roots: list[Path]) -> str | None:
    names = git(repo, ["log", "--diff-filter=A", "--name-only", "--pretty=format:", rev_range])
    if names.returncode != 0:
        return "Could not inspect the commits being pushed, so the push was blocked."
    paths = [
        line
        for line in names.stdout.splitlines()
        if line.strip() and is_personal_path(line.strip(), repo, roots, repo)
    ]
    if paths:
        return "Commits being pushed add personal card files (" + ", ".join(paths) + ")."
    patch = git(repo, ["log", "-p", "--unified=0", "--pretty=format:", rev_range])
    if patch.returncode != 0:
        return "Could not inspect commit contents, so the push was blocked."
    if added_share_urls(patch.stdout):
        return "Commits being pushed add a Yoto card URL."
    return None


def upstream_of(repo: Path, rev: str) -> str | None:
    proc = git(repo, ["rev-parse", "--abbrev-ref", f"{rev}@{{upstream}}"])
    if proc.returncode != 0:
        return None
    name = proc.stdout.strip()
    return name or None


def push_problems(repo: Path, rest: list[str], roots: list[Path]) -> str | None:
    scan_all = any(arg in {"--all", "--mirror"} for arg in rest)
    if scan_all:
        tip = tree_problems(repo, "HEAD", roots)
        if tip:
            return tip
        return range_problems(repo, "--all", roots)

    positionals: list[str] = []
    index = 0
    while index < len(rest):
        arg = rest[index]
        if arg.startswith("-"):
            if arg in {"-o", "--push-option", "--exec", "--receive-pack", "--repo"}:
                index += 2
                continue
            index += 1
            continue
        positionals.append(arg)
        index += 1

    remotes = set(git(repo, ["remote"]).stdout.split())
    refspecs = positionals[1:] if positionals and positionals[0] in remotes else positionals
    sources = []
    for spec in refspecs:
        src = spec.split(":", 1)[0]
        if src.startswith("+"):
            src = src[1:]
        if src:
            sources.append(src)
    if not sources:
        sources = ["HEAD"]

    for source in sources:
        tip = tree_problems(repo, source, roots)
        if tip:
            return tip
        upstream = upstream_of(repo, source)
        if upstream:
            problem = range_problems(repo, f"{upstream}..{source}", roots)
        else:
            problem = range_problems(repo, source, roots)
        if problem:
            return problem
    return None


def broad_add(rest: list[str]) -> bool:
    if any(arg in {"-A", "--all"} for arg in rest):
        return True
    specs = []
    skip_value = {"--pathspec-from-file", "--chmod"}
    index = 0
    while index < len(rest):
        arg = rest[index]
        if arg == "--":
            specs.extend(rest[index + 1 :])
            break
        if arg in skip_value and index + 1 < len(rest):
            index += 2
            continue
        if arg.startswith("-"):
            index += 1
            continue
        specs.append(arg)
        index += 1
    if not specs:
        return False
    return any(spec in {".", "./", "*", "./*", ":"} for spec in specs)


def forced(rest: list[str]) -> bool:
    return any(arg in {"-f", "--force"} or arg.startswith("--force=") for arg in rest)


def check_git(argv: list[str], cwd: Path, roots: list[Path]) -> str | None:
    parsed = parse_git(argv, cwd)
    if parsed is None:
        return None
    sub, rest, work = parsed
    repo = repo_root(work) or repo_root(cwd)
    if SHARE_URL.search(" ".join(argv)):
        return "The git command contains a Yoto card URL."

    if sub == "add":
        explicit = [
            arg
            for arg in non_options(["git", *rest])
            if is_personal_path(arg, work, roots, repo)
        ]
        if explicit:
            return "git add targets personal card files (" + ", ".join(explicit) + ")."
        if forced(rest) and (broad_add(rest) or not non_options(["git", *rest])):
            return "git add --force would stage ignored card files."
        if repo is not None and broad_add(rest) and not ignore_rules_active(repo):
            return "library/, backups/, or config.json is not gitignored, so a broad git add was blocked."
        return None

    if sub == "commit":
        if repo is None:
            return "Could not find the git repo, so the commit was blocked."
        return staged_problems(repo, roots)

    if sub == "push":
        if repo is None:
            return "Could not find the git repo, so the push was blocked."
        return push_problems(repo, rest, roots)

    if sub == "update-index":
        removing = any(arg in {"--remove", "--force-remove"} for arg in rest)
        adding = any(arg in {"--add", "--cacheinfo"} for arg in rest) or not removing
        if adding:
            explicit = [
                arg
                for arg in non_options(["git", *rest])
                if is_personal_path(arg, work, roots, repo)
            ]
            if explicit:
                return "git update-index would stage personal card files."
        return None

    if sub in {"apply", "am"}:
        for arg in non_options(argv):
            patch = Path(arg)
            if not patch.is_absolute():
                patch = work / patch
            if not patch.is_file() or patch.stat().st_size > 2_000_000:
                continue
            try:
                text = patch.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            if SHARE_URL.search(text) or "\nlibrary/" in "\n" + text or "\nbackups/" in "\n" + text:
                return "The patch adds personal card files or a Yoto card URL."
        return None

    return None


def check_transfer(argv: list[str], cwd: Path, roots: list[Path], repo: Path | None) -> str | None:
    name = Path(argv[0]).name
    if name not in TRANSFER and name not in CLOUD and name != "ssh":
        return None
    if SHARE_URL.search(" ".join(argv)):
        return f"{name} includes a Yoto card URL."
    args = non_options(argv)
    personal = [arg for arg in argv[1:] if is_personal_path(arg, cwd, roots, repo)]
    if not personal:
        return None
    if name in CLOUD or name == "ssh" or name == "scp":
        return f"{name} would send personal card files."
    if len(args) < 2:
        return f"{name} would send personal card files."
    dest = args[-1]
    dest_personal = is_personal_path(dest, cwd, roots, repo)
    if is_remote(dest) or not dest_personal:
        return f"{name} would move personal card files out of the library or backups."
    return None


def curl_uploads(argv: list[str]) -> bool:
    upload_flags = {
        "-T",
        "--upload-file",
        "-F",
        "--form",
        "-d",
        "--data",
        "--data-binary",
        "--data-raw",
        "--data-urlencode",
    }
    return any(
        arg in upload_flags or any(arg.startswith(flag + "=") for flag in upload_flags)
        for arg in argv
    )


def segment_network_upload(argv: list[str]) -> bool:
    name = Path(argv[0]).name
    if name in CLOUD or name in {"scp", "ssh", "rclone"}:
        return True
    if name == "curl":
        return curl_uploads(argv)
    if name == "gh" and len(argv) > 1 and argv[1] in {"release", "gist", "pr", "issue"}:
        return True
    if name == "rsync":
        args = non_options(argv)
        return bool(args) and is_remote(args[-1])
    return False


def check_curl(argv: list[str], cwd: Path, roots: list[Path], repo: Path | None) -> str | None:
    if Path(argv[0]).name != "curl":
        return None
    if not curl_uploads(argv):
        return None
    if SHARE_URL.search(" ".join(argv)):
        return "curl would send a Yoto card URL."
    if any(is_personal_path(arg, cwd, roots, repo) for arg in curl_file_args(argv)):
        return "curl would upload personal card files."
    return None


def curl_file_args(argv: list[str]) -> list[str]:
    """Arguments plus the file part of -F name=@file, -d @file, and name=<file."""
    found = list(argv)
    for arg in argv:
        for marker in ("=@", "=<"):
            if marker in arg:
                found.append(arg.split(marker, 1)[1].split(";", 1)[0])
        if arg.startswith(("@", "<")):
            found.append(arg[1:])
    return found


def check_gh(argv: list[str], cwd: Path, roots: list[Path], repo: Path | None) -> str | None:
    if Path(argv[0]).name != "gh":
        return None
    if SHARE_URL.search(" ".join(argv)):
        return "gh would publish a Yoto card URL."
    interesting = False
    if len(argv) >= 3 and argv[1] == "release" and argv[2] in {"upload", "create"}:
        interesting = True
    if len(argv) >= 3 and argv[1] == "gist" and argv[2] == "create":
        interesting = True
    if "--body-file" in argv:
        interesting = True
    if not interesting:
        return None
    if any(is_personal_path(arg, cwd, roots, repo) for arg in argv[1:]):
        return "gh would publish personal card files."
    return None


def redirect_leaks(command: str, cwd: Path, roots: list[Path], repo: Path | None) -> str | None:
    if ">" not in command:
        return None
    try:
        argv = shlex.split(command, posix=True)
    except ValueError:
        argv = command.split()
    before, _, _after = command.partition(">")
    try:
        before_argv = shlex.split(before, posix=True)
    except ValueError:
        before_argv = before.split()
    if any(is_personal_path(arg, cwd, roots, repo) for arg in before_argv):
        return "A redirect would copy personal card data into another file."
    if SHARE_URL.search(command) and any(is_personal_path(arg, cwd, roots, repo) for arg in argv):
        return "The command includes a Yoto card URL."
    return None


def evaluate_command(command: str, cwd: Path) -> str | None:
    command = unwrap_shell(command)
    repo = repo_root(cwd)
    roots = personal_roots(repo, cwd)
    if SHARE_URL.search(command) and re.search(
        r"\b(git\s+(add|commit|push|apply|am)|gh|curl|scp|rsync|rclone)\b",
        command,
    ):
        return "The command includes a Yoto card URL."
    saw_personal = False
    saw_upload = False
    for part in split_commands(command):
        leak = redirect_leaks(part, cwd, roots, repo)
        if leak:
            return leak
        try:
            argv = shlex.split(part, posix=True)
        except ValueError:
            if re.search(r"(^|[\s'\"=])(\./)?(library|backups|config\.json)(/|\s|'|\"|$)", part):
                return "Could not parse a command that mentions card files, so it was blocked."
            continue
        if not argv:
            continue
        if any(is_personal_path(arg, cwd, roots, repo) for arg in argv):
            saw_personal = True
        if segment_network_upload(argv):
            saw_upload = True
        reason = (
            check_git(argv, cwd, roots)
            or check_transfer(argv, cwd, roots, repo)
            or check_curl(argv, cwd, roots, repo)
            or check_gh(argv, cwd, roots, repo)
        )
        if reason:
            return reason
    if saw_personal and saw_upload:
        return "The command reads personal card files and also uploads them."
    return None


def tool_file(inp: dict) -> Path | None:
    for key in ("file_path", "notebook_path", "path"):
        raw = inp.get(key)
        if isinstance(raw, str) and raw.strip():
            return Path(raw)
    return None


def evaluate_tool(name: str, inp: dict, cwd: Path) -> str | None:
    lowered = name.lower()
    if lowered in READ_TOOLS or lowered.startswith("mcp__"):
        return None
    command = inp.get("command")
    if isinstance(command, str) and lowered == "bash":
        return evaluate_command(command, cwd)

    path = tool_file(inp)
    if path is None:
        return None
    if not path.is_absolute():
        path = cwd / path
    repo = repo_root(cwd)
    roots = personal_roots(repo, cwd)

    if path.name == ".gitignore" or path.as_posix().endswith("/.gitignore"):
        contents = inp.get("contents")
        if contents is None:
            contents = inp.get("content")
        if isinstance(contents, str):
            if not gitignore_protects(contents):
                return ".gitignore must keep ignoring library/, backups/, and config.json."
            return None
        old = inp.get("old_string")
        new = inp.get("new_string")
        if isinstance(old, str) and isinstance(new, str) and path.is_file():
            try:
                current = path.read_text(encoding="utf-8")
            except OSError:
                return "Could not read .gitignore, so the edit was blocked."
            if old not in current:
                return None
            projected = current.replace(old, new, 1)
            if not gitignore_protects(projected):
                return ".gitignore must keep ignoring library/, backups/, and config.json."
        return None

    destination_personal = any(inside(path, root) for root in roots)
    if path.name in PERSONAL_FILENAMES and not destination_personal:
        return "card.json and recovery.json stay inside library/ or backups/."

    blobs = []
    for key in ("contents", "content", "new_string", "new_source"):
        value = inp.get(key)
        if isinstance(value, str):
            blobs.append(value)
    if not destination_personal and any(SHARE_URL.search(blob) for blob in blobs):
        return "That edit would write a Yoto card URL into a project file."
    return None


def claude_main(data: dict) -> int:
    cwd = Path(data.get("cwd") or os.getcwd())
    name = data.get("tool_name") or ""
    inp = data.get("tool_input") or {}
    if not isinstance(inp, dict):
        inp = {}
    if not isinstance(name, str) or not name:
        return emit_claude(None)
    return emit_claude(evaluate_tool(name, inp, cwd))


def git_hook_main(mode: str) -> int:
    cwd = Path.cwd()
    repo = repo_root(cwd)
    if repo is None:
        sys.stderr.write("personal card hook: not a git repo, blocking.\n")
        return 1
    roots = personal_roots(repo, repo)
    if mode == "--git-pre-commit":
        reason = staged_problems(repo, roots)
    elif mode == "--git-pre-push":
        lines = [line.strip() for line in sys.stdin.read().splitlines() if line.strip()]
        reason = None
        if not lines:
            reason = push_problems(repo, [], roots)
        for line in lines:
            parts = line.split()
            if len(parts) < 4:
                reason = "Could not read the pre-push refs, so the push was blocked."
                break
            local_sha, remote_sha = parts[1], parts[3]
            if set(local_sha) <= {"0"}:
                continue
            reason = tree_problems(repo, local_sha, roots)
            if reason:
                break
            if set(remote_sha) <= {"0"}:
                reason = range_problems(repo, local_sha, roots)
            else:
                reason = range_problems(repo, f"{remote_sha}..{local_sha}", roots)
            if reason:
                break
    else:
        sys.stderr.write("personal card hook: unknown git mode.\n")
        return 1
    if reason:
        sys.stderr.write(USER_MESSAGE + "\n" + reason + "\n")
        return 1
    return 0


def main() -> int:
    if len(sys.argv) > 1 and sys.argv[1] in {"--git-pre-commit", "--git-pre-push"}:
        return git_hook_main(sys.argv[1])
    raw = sys.stdin.read()
    if not raw.strip():
        return emit_claude(None)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return emit_claude("The hook received invalid input and failed closed.")
    if not isinstance(data, dict):
        return emit_claude("The hook received unexpected input and failed closed.")
    return claude_main(data)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception as exc:
        if any(arg.startswith("--git-") for arg in sys.argv):
            sys.stderr.write(f"personal card hook failed closed: {exc}\n")
            raise SystemExit(1) from exc
        # A non-zero exit does not block a tool call, so deny explicitly.
        sys.stdout.write(deny_payload(f"The hook crashed and failed closed ({exc})."))
        raise SystemExit(0) from exc
