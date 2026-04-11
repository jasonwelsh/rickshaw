"""Rickshaw Context — RICKSHAW.md discovery, loading, and injection.

Mirrors Claude Code's CLAUDE.md pattern:
  1. Walk upward from CWD to discover instruction files
  2. Load user-level global instructions
  3. Process @include directives
  4. Inject into system prompt before each API call
  5. Memoize per session

Priority (lowest to highest):
  User:    ~/.rickshaw/RICKSHAW.md
  Project: RICKSHAW.md, .rickshaw/RICKSHAW.md, .rickshaw/rules/*.md
  Local:   RICKSHAW.local.md (private, not checked in)
"""
import glob
import os
import re
from datetime import datetime
from pathlib import Path
from functools import lru_cache

MAX_CONTENT_CHARS = 40000
MAX_INCLUDE_DEPTH = 5

# File extensions allowed for @include
TEXT_EXTENSIONS = {
    ".md", ".txt", ".py", ".js", ".ts", ".json", ".yaml", ".yml",
    ".toml", ".xml", ".csv", ".html", ".css", ".sql", ".sh", ".bat",
    ".ps1", ".cfg", ".ini", ".conf", ".env", ".log",
}


class ContextFile:
    """A discovered instruction file."""
    __slots__ = ("path", "type", "content", "parent")

    def __init__(self, path, file_type, content, parent=None):
        self.path = path
        self.type = file_type      # 'user', 'project', 'local'
        self.content = content
        self.parent = parent       # parent path if @included

    def __repr__(self):
        return f"ContextFile({self.type}: {self.path})"


class ContextLoader:
    """Discovers and loads RICKSHAW.md files, caches per session."""

    def __init__(self, cwd=None, home=None):
        self.cwd = cwd or os.getcwd()
        self.home = home or str(Path.home())
        self._cache = None
        self._cache_cwd = None

    def clear_cache(self):
        self._cache = None
        self._cache_cwd = None

    def get_context_files(self):
        """Discover and load all instruction files. Memoized per CWD."""
        if self._cache is not None and self._cache_cwd == self.cwd:
            return self._cache

        files = []
        processed = set()

        # 1. User-level: ~/.rickshaw/RICKSHAW.md
        user_dir = os.path.join(self.home, ".rickshaw")
        user_md = os.path.join(user_dir, "RICKSHAW.md")
        if os.path.isfile(user_md):
            files.extend(self._load_file(user_md, "user", processed))

        # User rules: ~/.rickshaw/rules/*.md
        user_rules = os.path.join(user_dir, "rules")
        if os.path.isdir(user_rules):
            for rule_file in sorted(glob.glob(os.path.join(user_rules, "*.md"))):
                files.extend(self._load_file(rule_file, "user", processed))

        # 2. Walk upward from CWD to root, collecting directories
        dirs = []
        current = os.path.abspath(self.cwd)
        while True:
            dirs.append(current)
            parent = os.path.dirname(current)
            if parent == current:
                break
            current = parent

        # Process from root DOWN to CWD (so CWD has highest priority)
        dirs.reverse()

        for d in dirs:
            # Project: RICKSHAW.md
            project_md = os.path.join(d, "RICKSHAW.md")
            if os.path.isfile(project_md):
                files.extend(self._load_file(project_md, "project", processed))

            # Project: .rickshaw/RICKSHAW.md
            dot_md = os.path.join(d, ".rickshaw", "RICKSHAW.md")
            if os.path.isfile(dot_md):
                files.extend(self._load_file(dot_md, "project", processed))

            # Project rules: .rickshaw/rules/*.md
            rules_dir = os.path.join(d, ".rickshaw", "rules")
            if os.path.isdir(rules_dir):
                for rule_file in sorted(glob.glob(os.path.join(rules_dir, "*.md"))):
                    files.extend(self._load_file(rule_file, "project", processed))

            # Local: RICKSHAW.local.md (private)
            local_md = os.path.join(d, "RICKSHAW.local.md")
            if os.path.isfile(local_md):
                files.extend(self._load_file(local_md, "local", processed))

        self._cache = files
        self._cache_cwd = self.cwd
        return files

    def _load_file(self, path, file_type, processed, depth=0, parent=None):
        """Load a file and process @include directives. Returns list of ContextFiles."""
        norm = os.path.normcase(os.path.abspath(path))
        if norm in processed:
            return []
        processed.add(norm)

        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                raw = f.read(MAX_CONTENT_CHARS + 1000)
        except (OSError, IOError):
            return []

        # Strip HTML comments
        content = re.sub(r"<!--.*?-->", "", raw, flags=re.DOTALL)

        # Strip frontmatter
        content = re.sub(r"^---\n.*?\n---\n", "", content, count=1, flags=re.DOTALL)

        # Process @include directives (not inside code blocks)
        results = []
        if depth < MAX_INCLUDE_DEPTH:
            includes = self._extract_includes(content, path)
            for inc_path in includes:
                ext = os.path.splitext(inc_path)[1].lower()
                if ext in TEXT_EXTENSIONS and os.path.isfile(inc_path):
                    results.extend(
                        self._load_file(inc_path, file_type, processed, depth + 1, path)
                    )

        # Truncate if too long
        if len(content) > MAX_CONTENT_CHARS:
            content = content[:MAX_CONTENT_CHARS] + "\n\n[truncated]"

        results.append(ContextFile(path, file_type, content.strip(), parent))
        return results

    def _extract_includes(self, content, parent_path):
        """Find @path directives in content. Returns resolved absolute paths."""
        parent_dir = os.path.dirname(os.path.abspath(parent_path))
        paths = []

        # Skip code blocks
        in_code = False
        for line in content.split("\n"):
            if line.strip().startswith("```"):
                in_code = not in_code
                continue
            if in_code:
                continue

            # Match @path patterns (not @mentions like @user)
            for match in re.finditer(r"(?:^|\s)@((?:[^\s\\]|\\ )+)", line):
                raw = match.group(1).replace("\\ ", " ")

                # Skip common non-file @ patterns
                if raw.startswith("http") or raw.startswith("{"):
                    continue

                # Resolve path
                if raw.startswith("~/"):
                    resolved = os.path.join(self.home, raw[2:])
                elif raw.startswith("/") or (len(raw) > 1 and raw[1] == ":"):
                    resolved = raw
                else:
                    if raw.startswith("./"):
                        raw = raw[2:]
                    resolved = os.path.join(parent_dir, raw)

                # Strip fragment
                if "#" in resolved:
                    resolved = resolved.split("#")[0]

                paths.append(os.path.abspath(resolved))

        return paths

    def build_context_block(self, extra_sections=None):
        """Build the full context injection string (like system-reminder)."""
        files = self.get_context_files()
        parts = []

        if files:
            parts.append("# Instructions")
            parts.append(
                "Codebase and user instructions are shown below. "
                "Be sure to adhere to these instructions."
            )

            type_desc = {
                "user": " (user's global instructions)",
                "project": " (project instructions)",
                "local": " (private project instructions)",
            }

            for f in files:
                desc = type_desc.get(f.type, "")
                rel = os.path.relpath(f.path, self.cwd) if f.type != "user" else f.path
                parts.append(f"\nContents of {rel}{desc}:\n")
                parts.append(f.content)

        # Extra sections (git status, date, etc.)
        if extra_sections:
            for key, value in extra_sections.items():
                parts.append(f"\n# {key}\n{value}")

        # Always add date
        parts.append(f"\n# currentDate\nToday's date is {datetime.now().strftime('%Y-%m-%d')}.")

        if not parts:
            return ""

        return "\n".join(parts)

    def summary(self):
        """Return a short summary of loaded context files."""
        files = self.get_context_files()
        if not files:
            return "No instruction files found."
        lines = []
        for f in files:
            size = len(f.content)
            inc = f" (@included from {os.path.basename(f.parent)})" if f.parent else ""
            lines.append(f"  [{f.type}] {f.path} ({size:,} chars){inc}")
        return "\n".join(lines)
