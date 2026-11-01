"""The docs only name commands, actions and options that exist, and their links
resolve.

Commands are looked for in code (backticks and fenced blocks) of every Markdown
file in the repository, so prose can say "the fx command" freely. Placeholders
(NAME, <name>, X) are skipped.
"""

import argparse
import re
import unittest
from pathlib import Path

from fxa import cli, layers, paths

REPO = paths.REPO
DOCS = sorted(
    {
        *REPO.glob("*.md"),
        *(REPO / "docs").glob("*.md"),
        *(REPO / "layers").rglob("*.md"),
        *REPO.glob(".claude/skills/*/SKILL.md"),
    }
)
FX = re.compile(r"(?:^|[\s;&|(])(?:\./|\.\\)?fx(?:\.cmd)?\s+(\S.*)")
STOP = {";", "&&", "||", "|", "#", ">", "2>&1"}


def code_lines(text):
    for block in re.findall(r"```[^\n]*\n(.*?)```", text, re.S):
        yield from block.splitlines()
    yield from re.findall(
        r"`([^`\n]+)`", re.sub(r"```.*?```", "", text, flags=re.S)
    )


def subparsers(parser):
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            return action.choices
    return None


def positional_choices(parser):
    for action in parser._actions:
        if (
            not action.option_strings
            and action.choices
            and not isinstance(action, argparse._SubParsersAction)
        ):
            return list(action.choices)
    return None


class DocsTest(unittest.TestCase):
    def setUp(self):
        self.root = cli.build_parser()

    def check_invocation(self, words):
        """Problems with one `fx ...` invocation, as a list of strings."""
        tokens = []
        for w in words:
            if w in STOP or w.startswith("#"):
                break
            tokens.append(w)
        problems = []
        parser, global_opts = self.root, set(self.root._option_string_actions)
        i = 0
        while i < len(tokens) and tokens[i].startswith(
            "-"
        ):  # global options before the command
            i += 2 if tokens[i] in ("-s", "--session") else 1
        if i >= len(tokens):
            return problems
        command = tokens[i]
        if not re.match(r"^[a-z][a-z-]*$", command):
            return problems  # a placeholder or prose
        choices = subparsers(parser)
        if command not in choices:
            return [f"unknown command `fx {command}`"]
        parser = choices[command]
        rest = tokens[i + 1 :]
        nested = subparsers(parser)
        options = set(parser._option_string_actions) | global_opts
        if nested is not None and rest and re.match(r"^[a-z][a-z-]*$", rest[0]):
            if rest[0] not in nested:
                return [f"unknown action `fx {command} {rest[0]}`"]
            options |= set(nested[rest[0]]._option_string_actions)
            rest = rest[1:]
        elif (
            nested is None
            and positional_choices(parser)
            and rest
            and re.match(r"^[a-z][a-z-]*$", rest[0])
        ):
            if rest[0] not in positional_choices(parser):
                problems.append(
                    f"`fx {command} {rest[0]}`: {rest[0]} is not one of "
                    f"{positional_choices(parser)}"
                )
        for word in rest:
            if re.match(r"^--?[A-Za-z][\w-]*", word):
                option = word.split("=", 1)[0]
                if option not in options:
                    problems.append(f"`fx {command}` has no option {option}")
        return problems

    def test_commands_in_docs_exist(self):
        problems = []
        for path in DOCS:
            for line in code_lines(path.read_text(encoding="utf-8")):
                for match in FX.finditer(line):
                    for problem in self.check_invocation(
                        match.group(1).split()
                    ):
                        problems.append(
                            f"{path.relative_to(REPO)}: {problem}  "
                            f"[{line.strip()}]"
                        )
        self.assertEqual(problems, [], "\n" + "\n".join(problems))

    def test_checker_catches_mistakes(self):
        self.assertTrue(self.check_invocation(["host"]))
        self.assertTrue(self.check_invocation(["session", "delete", "x"]))
        self.assertTrue(self.check_invocation(["server", "reboot"]))
        self.assertTrue(self.check_invocation(["chat", "--folow"]))
        self.assertEqual(
            self.check_invocation(
                ["session", "new", "NAME", "--mode", "coop", "--admin", "<you>"]
            ),
            [],
        )
        self.assertEqual(
            self.check_invocation(["-s", "game", "--json", "state"]), []
        )

    def test_links_resolve(self):
        problems = []
        for path in DOCS:
            for target in re.findall(
                r"\]\(([^)\s]+)\)", path.read_text(encoding="utf-8")
            ):
                if re.match(r"^[a-z]+:", target) or target.startswith("#"):
                    continue
                if not (path.parent / target.split("#", 1)[0]).exists():
                    problems.append(
                        f"{path.relative_to(REPO)}: broken link {target}"
                    )
        self.assertEqual(problems, [], "\n" + "\n".join(problems))

    def test_knowledge_headers(self):
        for path in sorted((REPO / "layers").rglob("knowledge/**/*.md")):
            with self.subTest(item=str(path.relative_to(REPO))):
                meta, body = layers.parse_front(
                    path.read_text(encoding="utf-8")
                )
                self.assertTrue(meta.get("title"), "no title in the header")
                self.assertTrue(body.strip(), "empty body")
                if meta.get("game"):
                    self.assertTrue(
                        layers.version_ok(meta["game"], (2, 0, 77))
                        in (True, False)
                    )
                self.assertNotIn(
                    "/home/", body, "machine-specific path in shipped knowledge"
                )


if __name__ == "__main__":
    unittest.main()
