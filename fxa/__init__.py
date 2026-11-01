"""factorio-agent: lets an LLM agent play Factorio through a text interface. See AGENTS.md."""

__version__ = "0.1.0.dev0"

# Lowest game version the in-game script supports, and the newest one it was tested on.
GAME_MIN = (2, 0, 0)
GAME_TESTED = (2, 0, 77)


def build_info():
    """Where this copy comes from: a release archive (commit and date) or a git checkout."""
    from fxa import _build
    if not _build.COMMIT.startswith("$"):
        return f"(release archive, commit {_build.COMMIT[:10]}, {_build.DATE})"
    import subprocess
    from pathlib import Path
    try:
        repo = Path(__file__).resolve().parent.parent
        sha = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=repo, capture_output=True, text=True,
                             timeout=10).stdout.strip()
        dirty = subprocess.run(["git", "status", "--porcelain"], cwd=repo, capture_output=True, text=True,
                               timeout=10).stdout.strip()
        if sha:
            return f"(git checkout {sha}{', with local changes' if dirty else ''})"
    except (OSError, subprocess.SubprocessError):
        pass
    return "(source copy)"
