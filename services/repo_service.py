from __future__ import annotations
import os
import tempfile
from pathlib import Path
import git

CODE_EXTENSIONS = {
    ".py", ".js", ".ts", ".tsx", ".jsx", ".go", ".java", ".rb", ".rs",
    ".cpp", ".c", ".h", ".cs", ".php", ".swift", ".kt", ".scala",
    ".yaml", ".yml", ".toml", ".json", ".md", ".html", ".css",
}
ENTRY_POINT_NAMES = {
    "main.py", "app.py", "server.py", "index.py", "run.py",
    "manage.py", "main.js", "app.js", "server.js", "index.js",
    "main.ts", "app.ts", "server.ts", "index.ts",
}
MAX_FILE_BYTES = 50_000  # truncate files larger than 50 KB


class RepoService:
    def __init__(self, max_files: int = 50, recent_commits: int = 10):
        self.max_files = max_files
        self.recent_commits = recent_commits

    def clone_and_select(self, repo_url: str) -> tuple[str, list[str]]:
        """Clone repo, pin SHA, return (commit_sha, list[formatted file content])."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = git.Repo.clone_from(repo_url, tmpdir)
            commit_sha = repo.head.commit.hexsha
            selected_paths = self._select_files(repo, tmpdir)
            contents = []
            for path in selected_paths:
                rel = os.path.relpath(path, tmpdir)
                try:
                    with open(path, "r", encoding="utf-8", errors="ignore") as fh:
                        text = fh.read(MAX_FILE_BYTES)
                    contents.append(f"### {rel}\n{text}")
                except OSError:
                    pass
            return commit_sha, contents

    def _select_files(self, repo: git.Repo, root: str) -> list[str]:
        selected: list[str] = []
        seen: set[str] = set()

        def add(path: str) -> None:
            if path not in seen and os.path.isfile(path):
                seen.add(path)
                selected.append(path)

        # Priority 1: entry points (recursive search)
        for ep_name in ENTRY_POINT_NAMES:
            for match in Path(root).rglob(ep_name):
                add(str(match))

        # Priority 2: files changed in recent commits
        try:
            for commit in repo.iter_commits(max_count=self.recent_commits):
                for changed_file in commit.stats.files:
                    add(os.path.join(root, changed_file))
        except git.GitCommandError:
            pass

        # Priority 3: fill remaining slots with smallest code files
        if len(selected) < self.max_files:
            candidates = sorted(
                (p for p in Path(root).rglob("*") if p.is_file()
                 and p.suffix in CODE_EXTENSIONS and str(p) not in seen),
                key=lambda p: p.stat().st_size,
            )
            for path in candidates:
                if len(selected) >= self.max_files:
                    break
                add(str(path))

        return selected[: self.max_files]
