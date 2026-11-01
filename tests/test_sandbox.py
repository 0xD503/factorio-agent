"""The skill sandbox: the language subset works, and nothing outside it is reachable."""

import unittest

from fxa import sandbox
from fxa.sandbox import Interpreter, SandboxError


def run(source, host=None, **budget):
    out = []
    interp = Interpreter(host or {}, budget=sandbox.Budget(**budget), output=out.append)
    scope = interp.run(source)
    return scope, "".join(out), interp


def value(source, host=None, **budget):
    scope, _, _ = run(source, host, **budget)
    return scope.get("result")


class LanguageTest(unittest.TestCase):
    def test_arithmetic_and_strings(self):
        self.assertEqual(value("result = (2 + 3) * 4 // 3 - 1"), 5)
        self.assertEqual(value("result = 7 / 2"), 3.5)
        self.assertEqual(value("result = f'{1 + 1}x{3.14159:.2f}'"), "2x3.14")
        self.assertEqual(value("result = 'a,b'.split(',') + ['c']"), ["a", "b", "c"])
        self.assertEqual(value("result = '-'.join(['x', 'y'])"), "x-y")

    def test_control_flow(self):
        src = """
total = 0
for i in range(10):
    if i == 7:
        break
    if i % 2:
        continue
    total += i
n = 0
while n < 5:
    n += 1
result = (total, n)
"""
        self.assertEqual(value(src), (12, 5))

    def test_functions_closures_lambdas(self):
        src = """
def make(k, scale=2, *rest, **opts):
    def inner(v):
        return v * k * scale + len(rest) + len(opts)
    return inner
f = make(3, 1, 9, 9, flag=True)
g = lambda a, b=1: a - b
result = [f(2), g(5), g(5, b=4)]
"""
        self.assertEqual(value(src), [9, 4, 1])

    def test_comprehensions_and_unpacking(self):
        src = """
pairs = [(x, y) for x in range(3) for y in range(3) if x < y]
squares = {x: x * x for x in range(4)}
first, *middle, last = [1, 2, 3, 4, 5]
evens = {x for x in range(6) if x % 2 == 0}
result = (pairs, squares[3], middle, last, sorted(evens))
"""
        self.assertEqual(value(src), ([(0, 1), (0, 2), (1, 2)], 9, [2, 3, 4], 5, [0, 2, 4]))

    def test_data_methods(self):
        src = """
d = {"a": 1}
d.setdefault("b", 2)
d.update({"c": 3})
xs = [3, 1, 2]
xs.sort(key=lambda v: -v)
result = (sorted(d.keys()), d.get("z", 0), xs, max([1, 5, 2], key=lambda v: -v))
"""
        self.assertEqual(value(src), (["a", "b", "c"], 0, [3, 2, 1], 1))

    def test_host_functions_get_and_return_plain_data(self):
        seen = []

        def remember(x, flag=None):
            seen.append((x, flag))
            return {"echo": x}
        self.assertEqual(value("result = remember([1, (2, 3)], flag=True)", {"remember": remember}), {"echo": [1, [2, 3]]})
        self.assertEqual(seen, [([1, [2, 3]], True)])

    def test_print_is_captured_and_cleaned(self):
        _, out, _ = run("print('a', 1, [2])\nprint('\\x1b[31mred')")
        self.assertEqual(out, "a 1 [2][31mred")

    def test_errors_carry_line_numbers(self):
        with self.assertRaisesRegex(SandboxError, "line 3: ZeroDivisionError"):
            run("x = 1\ny = 0\nz = x / y")
        with self.assertRaisesRegex(SandboxError, "line 1: KeyError"):
            run("result = {}['missing']")
        with self.assertRaisesRegex(SandboxError, "boom"):
            run("fail('boom')")
        with self.assertRaisesRegex(SandboxError, "not defined"):
            run("result = undefined_name")


class EscapeTest(unittest.TestCase):
    """Each of these is a known way out of naive Python sandboxes."""

    ATTEMPTS = [
        "import os",
        "from os import system",
        "__import__('os')",
        "result = ().__class__.__bases__[0].__subclasses__()",
        "result = [].__class__",
        "x = 'abc'\nresult = x.__len__()",
        "result = (lambda: 0).__globals__",
        "result = getattr([], 'append')",
        "result = open('/etc/passwd').read()",
        "result = eval('1')",
        "result = exec('x = 1')",
        "result = compile('1', 'x', 'eval')",
        "result = globals()",
        "result = vars()",
        "result = type(1)",
        "result = '{0.__class__}'.format(1)",
        "result = 'x'.format_map({})",
        "class A:\n    pass",
        "try:\n    x = 1\nexcept Exception:\n    pass",
        "with x as y:\n    pass",
        "def f():\n    global x",
        "def f():\n    yield 1",
        "async def f():\n    pass",
        "x = [1]\ndel x[0]",
        "x = {}\nx.y = 1",
        "result = b'bytes'",
        "@decorator\ndef f():\n    pass",
        "result = print.__self__",
        "result = range(3).start",
        "result = [].append",
        "result = __builtins__",
        "result = __name__",
    ]

    def test_attempts_are_refused(self):
        for source in self.ATTEMPTS:
            with self.subTest(source=source), self.assertRaises(SandboxError):
                run(source)

    def test_host_values_cannot_leak_objects(self):
        class Secret:
            password = "hunter2"

        result = value("result = leak()", {"leak": lambda: {"obj": Secret(), "list": [Secret]}})
        self.assertIsInstance(result["obj"], str)
        self.assertIsInstance(result["list"][0], str)

    def test_functions_cannot_be_passed_to_host(self):
        with self.assertRaisesRegex(SandboxError, "cannot pass"):
            run("def f():\n    pass\nresult = sink(f)", {"sink": lambda x: x})

    def test_host_name_must_be_public(self):
        with self.assertRaises(ValueError):
            Interpreter({"_private": lambda: 1})


class LimitTest(unittest.TestCase):
    def test_infinite_loop_hits_step_limit(self):
        with self.assertRaisesRegex(SandboxError, "step limit"):
            run("while True:\n    pass", max_steps=20_000)

    def test_runaway_recursion(self):
        with self.assertRaisesRegex(SandboxError, "nested|deep"):
            run("def f(n):\n    return f(n + 1)\nf(0)")

    def test_big_values_are_refused(self):
        bombs = [
            "result = 'x' * (10 ** 7)",
            "result = [0] * (10 ** 7)",
            "result = 10 ** (10 ** 6)",
            "result = 1 << (10 ** 6)",
            "result = list(range(10 ** 8))",
            "s = 'x' * 900000\nresult = s + s",
            "s = 'ab' * 400000\nresult = s.replace('a', 'aaaa')",
            "result = ','.join(['x' * 900000, 'y' * 900000])",
            "result = f'{1:>100000000}'",
            "result = '%d' % 5",
            "result = sum([[1], [2]], [])",
        ]
        for source in bombs:
            with self.subTest(source=source), self.assertRaises(SandboxError):
                run(source)

    def test_self_referencing_list_is_safe_to_print(self):
        with self.assertRaises(SandboxError):
            run("a = []\na.append(a)\nprint(a)")

    def test_memory_limit(self):
        src = "keep = []\nfor i in range(200):\n    keep.append([i] * 900000)"
        with self.assertRaisesRegex(SandboxError, "memory"):
            run(src, max_memory=64 * 1024 * 1024)

    def test_shared_budget_counts_steps(self):
        _, _, interp = run("x = 0\nfor i in range(100):\n    x += i")
        self.assertGreater(interp.budget.steps, 300)


if __name__ == "__main__":
    unittest.main()
