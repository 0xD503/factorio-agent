"""Every text file in the repository follows .editorconfig: UTF-8, LF line
endings (CRLF for .cmd), a final newline, spaces instead of tabs, no trailing
spaces (except Markdown and the verbatim LICENSE), and at most 80 characters a
line (except Markdown table rows, which cannot be wrapped, and LICENSE)."""

import subprocess
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SKIP_DIRS = {".git", "dist", "__pycache__", ".venv"}


def files():
    try:
        listed = subprocess.run(
            ["git", "ls-files"],
            cwd=REPO,
            capture_output=True,
            text=True,
            timeout=30,
        ).stdout.split("\n")
        found = [
            REPO / name for name in listed if name and (REPO / name).is_file()
        ]
        if found:
            return found
    except (OSError, subprocess.SubprocessError):
        pass
    return [
        p
        for p in REPO.rglob("*")
        if p.is_file() and not SKIP_DIRS.intersection(p.relative_to(REPO).parts)
    ]


class StyleTest(unittest.TestCase):
    def test_editorconfig_rules(self):
        problems = []
        for path in files():
            data = path.read_bytes()
            if b"\0" in data:
                continue  # binary
            name = path.relative_to(REPO).as_posix()
            try:
                text = data.decode("utf-8")
            except UnicodeDecodeError:
                problems.append(f"{name}: not UTF-8")
                continue
            if not text:
                continue
            crlf = path.suffix == ".cmd"
            lines = text.split("\r\n" if crlf else "\n")
            if crlf and "\n" in text.replace("\r\n", ""):
                problems.append(f"{name}: needs CRLF line endings")
            if not crlf and "\r" in text:
                problems.append(
                    f"{name}: has CR characters (needs LF line endings)"
                )
            if lines[-1] != "":
                problems.append(f"{name}: no newline at the end")
            for number, line in enumerate(lines, 1):
                if "\t" in line:
                    problems.append(f"{name}:{number}: tab")
                table_row = path.suffix == ".md" and line.lstrip()[:1] == "|"
                if len(line) > 80 and not table_row and path.name != "LICENSE":
                    problems.append(f"{name}:{number}: {len(line)} > 80 chars")
                if (
                    line != line.rstrip()
                    and path.suffix != ".md"
                    and path.name != "LICENSE"
                ):
                    problems.append(f"{name}:{number}: trailing whitespace")
        self.assertEqual(problems, [], "\n" + "\n".join(problems[:50]))

    def test_editorconfig_present(self):
        text = (REPO / ".editorconfig").read_text(encoding="utf-8")
        for rule in (
            "root = true",
            "end_of_line = lf",
            "insert_final_newline = true",
            "indent_style = space",
            "indent_size = 4",
            "charset = utf-8",
            "trim_trailing_whitespace = true",
            "max_line_length = 80",
        ):
            self.assertIn(rule, text)


if __name__ == "__main__":
    unittest.main()
