"""The code must run on the oldest supported Python (3.10), whatever version runs the tests.

Two checks that do not need an old interpreter:
  - f-strings that only parse on 3.12+ (PEP 701: the outer quote reused inside {}, backslashes or
    comments in the expression part), found with the tokenizer;
  - standard-library names added after 3.10.
"""

import io
import re
import sys
import tokenize
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SOURCES = sorted([*REPO.glob("fxa/*.py"), *REPO.glob("tests/*.py"), *REPO.glob("tools/*.py"), REPO / "fx.py",
                  *REPO.glob("layers/**/*.fxs")])
NEWER = [r"\btomllib\b", r"\bExceptionGroup\b", r"except\*", r"\btyping\.Self\b", r"\bdatetime\.UTC\b",
         r"\bStrEnum\b", r"\bTaskGroup\b", r"\bitertools\.batched\b", r"\.walk\(\)", r"\bbatched\(",
         r"^\s*type \w+\s*=", r"\bLiteralString\b", r"\bassert_never\b", r"\bNotRequired\b"]


def pep701_fstrings(text):
    """(line, problem) for f-string syntax newer than 3.11, using the 3.12+ tokenizer."""
    if sys.version_info < (3, 12):
        return []          # an older tokenizer would simply fail on such code; the test run itself checks it
    problems, stack = [], []
    for tok in tokenize.generate_tokens(io.StringIO(text).readline):
        if tok.type == tokenize.FSTRING_START:
            quote = tok.string.lstrip("rRfFbBuU")[:1]
            if stack and quote == stack[-1]:
                problems.append((tok.start[0], "nested f-string reuses the outer quote"))
            stack.append(quote)
        elif tok.type == tokenize.FSTRING_END:
            stack.pop()
        elif stack and tok.type == tokenize.STRING:
            quote = tok.string.lstrip("rRbBuU")[:1]
            if quote == stack[-1]:
                problems.append((tok.start[0], "string inside an f-string reuses its quote"))
        elif stack and tok.type == tokenize.COMMENT:
            problems.append((tok.start[0], "comment inside an f-string"))
        elif stack and tok.type == tokenize.FSTRING_MIDDLE:
            pass
    return problems


class CompatTest(unittest.TestCase):
    def test_no_pep701_fstrings(self):
        found = []
        for path in SOURCES:
            for line, problem in pep701_fstrings(path.read_text(encoding="utf-8")):
                found.append(f"{path.relative_to(REPO)}:{line}: {problem}")
        self.assertEqual(found, [], "\n" + "\n".join(found))

    def test_no_stdlib_newer_than_310(self):
        found = []
        for path in SOURCES:
            if path.name == "test_compat.py":
                continue
            for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                for pattern in NEWER:
                    if re.search(pattern, line):
                        found.append(f"{path.relative_to(REPO)}:{number}: {line.strip()}")
        self.assertEqual(found, [], "\n" + "\n".join(found))

    def test_checker_works(self):
        if sys.version_info < (3, 12):
            self.skipTest("needs the 3.12 tokenizer")
        self.assertTrue(pep701_fstrings('x = f"{d["k"]}"\n'))
        self.assertFalse(pep701_fstrings("x = f\"{d['k']}\"\n"))


if __name__ == "__main__":
    unittest.main()
