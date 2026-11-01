"""An interpreter for a safe subset of Python, used to run skills.

Skills may come from other people (a shared session folder, a pull request), so they are
never run as Python. This module parses them with `ast` and walks the tree itself, allowing:

  - literals, names, arithmetic, comparisons, and/or/not, if/for/while/break/continue/pass,
    def/return/lambda, list/set/dict comprehensions, f-strings, subscripts and slices, assert
  - calls to the builtins in BUILTINS, to the functions the host passes in (the game API),
    to functions the script defines, and to the plain-data methods in METHODS
  - values: None, bool, int, float, str, list, tuple, dict, set, range, functions

Not allowed: import, class, try/raise, with, global/nonlocal, del, attribute access other
than those methods, names starting with "__", decorators, async, yield. A script cannot
reach files, the network, processes, or Python objects; all it can do is call the host
functions it was given.

Work is bounded by a step budget, CPU time, call depth, memory (tracemalloc), and caps on
the length of strings and collections and the size of integers. Exceeding any of them stops
the script with a SandboxError.
"""

import ast
import math
import time
import tracemalloc

# Default limits; the user can raise them for long-running skills (fx skill run --max-steps).
MAX_STEPS = 10_000_000
MAX_CPU_SECONDS = 300.0
MAX_DEPTH = 40
MAX_LEN = 1_000_000          # characters in a string, items in a collection
MAX_INT_BITS = 8192
MAX_MEMORY = 512 * 1024 * 1024
MAX_SOURCE = 400_000
MAX_OUTPUT = 1_000_000
MAX_FORMAT_WIDTH = 1000


class SandboxError(Exception):
    """A script broke a rule, hit a limit, or failed at run time."""


class _Break(Exception):
    pass


class _Continue(Exception):
    pass


class _Return(Exception):
    def __init__(self, value):
        self.value = value


ALLOWED = {
    ast.Module, ast.Expr, ast.Assign, ast.AugAssign, ast.If, ast.For, ast.While, ast.Break, ast.Continue,
    ast.Pass, ast.FunctionDef, ast.Return, ast.Lambda, ast.arguments, ast.arg, ast.keyword, ast.Assert,
    ast.Name, ast.Load, ast.Store, ast.Constant, ast.List, ast.Tuple, ast.Dict, ast.Set,
    ast.BinOp, ast.UnaryOp, ast.BoolOp, ast.Compare, ast.IfExp, ast.Call, ast.Attribute, ast.Subscript, ast.Slice,
    ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp, ast.comprehension, ast.JoinedStr, ast.FormattedValue,
    ast.Starred,
    ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv, ast.Mod, ast.Pow, ast.LShift, ast.RShift,
    ast.BitAnd, ast.BitOr, ast.BitXor, ast.USub, ast.UAdd, ast.Not, ast.Invert, ast.And, ast.Or,
    ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE, ast.In, ast.NotIn, ast.Is, ast.IsNot,
}

METHODS = {
    str: {"lower", "upper", "strip", "lstrip", "rstrip", "split", "rsplit", "splitlines", "startswith", "endswith",
          "replace", "join", "find", "rfind", "count", "index", "isdigit", "isalpha", "isalnum", "isspace",
          "title", "capitalize", "partition", "rpartition"},
    list: {"append", "extend", "insert", "pop", "remove", "index", "count", "sort", "reverse", "copy", "clear"},
    dict: {"get", "keys", "values", "items", "pop", "setdefault", "update", "copy", "clear"},
    set: {"add", "discard", "remove", "pop", "union", "intersection", "difference", "issubset", "issuperset",
          "copy", "clear", "update"},
    tuple: {"index", "count"},
}
METHOD_NAMES = set().union(*METHODS.values())
DATA = (type(None), bool, int, float, str, list, tuple, dict, set, range)


def validate(tree):
    """Reject anything outside the subset before running a single step. Returns a list of problems."""
    problems = []
    parents = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parents[child] = node
    count = 0
    for node in ast.walk(tree):
        count += 1
        line = getattr(node, "lineno", "?")
        if type(node) not in ALLOWED:
            problems.append(f"line {line}: {type(node).__name__} is not allowed in skills")
            continue
        if isinstance(node, ast.Name) and node.id.startswith("__"):
            problems.append(f"line {line}: names starting with '__' are not allowed ({node.id})")
        elif isinstance(node, ast.arg) and node.arg.startswith("__"):
            problems.append(f"line {line}: names starting with '__' are not allowed ({node.arg})")
        elif isinstance(node, ast.keyword) and node.arg and node.arg.startswith("__"):
            problems.append(f"line {line}: names starting with '__' are not allowed ({node.arg})")
        elif isinstance(node, ast.FunctionDef):
            if node.decorator_list:
                problems.append(f"line {line}: decorators are not allowed")
            if node.name.startswith("__"):
                problems.append(f"line {line}: names starting with '__' are not allowed ({node.name})")
        elif isinstance(node, ast.Attribute):
            parent = parents.get(node)
            if node.attr.startswith("_") or node.attr not in METHOD_NAMES:
                problems.append(f"line {line}: .{node.attr} is not allowed (only plain list/dict/str/set methods)")
            elif not (isinstance(parent, ast.Call) and parent.func is node):
                problems.append(f"line {line}: .{node.attr} can only be called, not read")
            if not isinstance(node.ctx, ast.Load):
                problems.append(f"line {line}: attributes cannot be assigned")
        elif isinstance(node, ast.Constant) and not isinstance(node.value, (type(None), bool, int, float, str)):
            problems.append(f"line {line}: {type(node.value).__name__} constants are not allowed")
        elif isinstance(node, (ast.Assign, ast.AugAssign)):
            for target in (node.targets if isinstance(node, ast.Assign) else [node.target]):
                for sub in ast.walk(target):
                    if isinstance(sub, ast.Attribute):
                        problems.append(f"line {line}: attributes cannot be assigned")
    if count > 200_000:
        problems.append("script too large")
    return problems


def parse(source, filename="<skill>"):
    if len(source) > MAX_SOURCE:
        raise SandboxError(f"{filename}: script larger than {MAX_SOURCE} characters")
    try:
        tree = ast.parse(source, filename=filename)
    except SyntaxError as err:
        raise SandboxError(f"{filename}: line {err.lineno}: {err.msg}") from None
    problems = validate(tree)
    if problems:
        raise SandboxError(f"{filename}: " + "; ".join(problems[:10]))
    return tree


class Function:
    __slots__ = ("name", "node", "defaults", "kw_defaults", "scopes", "interp", "is_lambda")

    def __init__(self, name, node, defaults, kw_defaults, scopes, interp, is_lambda=False):
        self.name, self.node, self.defaults, self.kw_defaults = name, node, defaults, kw_defaults
        self.scopes, self.interp, self.is_lambda = scopes, interp, is_lambda

    def __repr__(self):
        return f"<function {self.name}>"


class HostFunction:
    """A function the host makes available. It receives and returns plain data only."""
    __slots__ = ("name", "fn", "raw")

    def __init__(self, name, fn, raw=False):
        self.name, self.fn, self.raw = name, fn, raw

    def __repr__(self):
        return f"<builtin {self.name}>"


class Budget:
    """Limits shared by a script and the skills it calls."""

    def __init__(self, max_steps=None, max_cpu=None, max_memory=MAX_MEMORY):
        self.max_steps = max_steps or MAX_STEPS
        self.max_cpu = max_cpu or MAX_CPU_SECONDS
        self.max_memory = max_memory
        self.steps = 0
        self.depth = 0
        self.host_cpu = 0.0
        self.cpu_start = time.process_time()
        self.output = 0
        self.grown = 0

    def grow(self, n):
        """Called for every large value created; checks memory every million items or so."""
        self.grown += n
        if self.grown > 1_000_000:
            self.grown = 0
            self.check()

    def check(self):
        if self.steps > self.max_steps:
            raise SandboxError(f"step limit reached ({self.max_steps}); raise it with --max-steps if the skill is meant to run that long")
        if time.process_time() - self.cpu_start - self.host_cpu > self.max_cpu:
            raise SandboxError(f"CPU time limit reached ({self.max_cpu:.0f}s)")
        if tracemalloc.is_tracing() and tracemalloc.get_traced_memory()[0] > self.max_memory:
            raise SandboxError(f"memory limit reached ({self.max_memory // 2**20} MB)")


# Budgets of the scripts running now (a skill calling a skill nests them).
_ACTIVE = []


def _size_ok(value):
    if isinstance(value, (str, list, tuple, dict, set)):
        n = len(value)
        if n > MAX_LEN:
            raise SandboxError(f"value too large ({n} items; at most {MAX_LEN})")
        if n > 4096 and _ACTIVE:
            _ACTIVE[-1].grow(n)
    if isinstance(value, int) and not isinstance(value, bool) and value.bit_length() > MAX_INT_BITS:
        raise SandboxError(f"integer too large (more than {MAX_INT_BITS} bits)")
    return value


def safe_repr(value, limit=MAX_LEN):
    """repr() that refuses to build huge strings (shared sub-lists can make a repr explode)."""
    out, size = [], [0]

    def put(text):
        size[0] += len(text)
        if size[0] > limit:
            raise SandboxError("text too long")
        out.append(text)

    def walk(v, depth):
        if depth > 50:
            raise SandboxError("structure nested too deeply")
        if isinstance(v, (list, tuple, set)):
            open_, close = {list: "[]", tuple: "()", set: "{}"}[type(v)]
            if isinstance(v, set) and not v:
                put("set()")
                return
            put(open_[0])
            for index, item in enumerate(v):
                if index:
                    put(", ")
                walk(item, depth + 1)
            if isinstance(v, tuple) and len(v) == 1:
                put(",")
            put(close[-1])
        elif isinstance(v, dict):
            put("{")
            for index, (key, item) in enumerate(v.items()):
                if index:
                    put(", ")
                walk(key, depth + 1)
                put(": ")
                walk(item, depth + 1)
            put("}")
        elif isinstance(v, (Function, HostFunction)):
            put(repr(v))
        else:
            put(repr(v))

    walk(value, 0)
    return "".join(out)


def safe_str(value=""):
    if isinstance(value, str):
        return value
    if isinstance(value, (bool, int, float, type(None))):
        return _size_ok(str(value))
    return safe_repr(value)


def clean_text(text):
    """Drop control characters (terminal escape sequences) from text a script prints."""
    return "".join(c for c in text if c >= " " or c in "\n\t")


def _check_format_spec(spec):
    import re
    for number in re.findall(r"\d+", spec):
        if int(number) > MAX_FORMAT_WIDTH:
            raise SandboxError(f"format width or precision above {MAX_FORMAT_WIDTH}")


def sanitize(value, depth=0):
    """Host results become plain data."""
    if depth > 60:
        raise SandboxError("host value nested too deeply")
    if isinstance(value, (type(None), bool, int, float, str)):
        return value
    if isinstance(value, dict):
        return {(k if isinstance(k, (str, int, float, bool)) else str(k)): sanitize(v, depth + 1) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [sanitize(v, depth + 1) for v in value]
    if isinstance(value, set):
        return {v for v in value if isinstance(v, (str, int, float, bool))}
    return str(value)


def _plain(value, depth=0):
    """Script values handed to the host: plain data, no functions."""
    if depth > 60:
        raise SandboxError("value nested too deeply")
    if isinstance(value, (type(None), bool, int, float, str)):
        return value
    if isinstance(value, dict):
        return {k: _plain(v, depth + 1) for k, v in value.items()}
    if isinstance(value, (list, tuple, set, range)):
        return [_plain(v, depth + 1) for v in value]
    raise SandboxError(f"cannot pass a {type(value).__name__} to a game function")


class Interpreter:
    def __init__(self, host=None, budget=None, output=None, filename="<skill>"):
        self.budget = budget or Budget()
        self.filename = filename
        self.output = output or (lambda text: print(text, flush=True))
        self.globals = {}
        self.builtins = self._builtins()
        for name, fn in (host or {}).items():
            if name.startswith("_"):
                raise ValueError(f"host name {name!r} starts with '_'")
            self.builtins[name] = fn if isinstance(fn, (HostFunction, Function)) else HostFunction(name, fn)

    # -- running
    def run(self, source):
        tree = parse(source, self.filename)
        started = not tracemalloc.is_tracing()
        if started:
            tracemalloc.start()
        _ACTIVE.append(self.budget)
        try:
            self._block(tree.body, [self.globals])
        except _Return:
            raise SandboxError(f"{self.filename}: return outside a function") from None
        except (_Break, _Continue):
            raise SandboxError(f"{self.filename}: break/continue outside a loop") from None
        except RecursionError:
            raise SandboxError(f"{self.filename}: nested too deeply") from None
        finally:
            _ACTIVE.pop()
            if started:
                tracemalloc.stop()
        return self.globals

    def call(self, fn, args=(), kwargs=None):
        """Call a script function (e.g. main) from the host."""
        started = not tracemalloc.is_tracing()
        if started:
            tracemalloc.start()
        _ACTIVE.append(self.budget)
        try:
            return self._call(fn, list(args), dict(kwargs or {}), 0)
        except RecursionError:
            raise SandboxError(f"{self.filename}: nested too deeply") from None
        finally:
            _ACTIVE.pop()
            if started:
                tracemalloc.stop()

    # -- builtins
    def _builtins(self):
        def fn_arg(f):
            if f is None:
                return None
            if isinstance(f, (Function, HostFunction)):
                return lambda *a: self._call(f, list(a), {}, getattr(f, "lineno", 0))
            raise SandboxError("key must be a function")

        def b_sorted(items, key=None, reverse=False):
            return sorted(items, key=fn_arg(key), reverse=bool(reverse))

        def b_max(*items, key=None, default=None):
            seq = items[0] if len(items) == 1 else items
            if default is not None and not seq:
                return default
            return max(seq, key=fn_arg(key)) if key else max(seq)

        def b_min(*items, key=None, default=None):
            seq = items[0] if len(items) == 1 else items
            if default is not None and not seq:
                return default
            return min(seq, key=fn_arg(key)) if key else min(seq)

        def b_sum(items, start=0):
            items = list(items)
            if not all(isinstance(v, (int, float)) for v in items) or not isinstance(start, (int, float)):
                raise SandboxError("sum() adds numbers only")
            return _size_ok(sum(items, start))

        def b_range(*args):
            if not all(isinstance(a, int) for a in args):
                raise SandboxError("range() takes integers")
            r = range(*args)
            if len(r) > MAX_LEN:
                raise SandboxError(f"range of more than {MAX_LEN} numbers")
            return r

        def b_int(value=0, base=None):
            if isinstance(value, str) and len(value) > 1000:
                raise SandboxError("number text too long")
            return int(value) if base is None else int(value, base)

        def b_print(*args, sep=" ", end=""):
            text = clean_text(str(sep).join(safe_str(a) for a in args) + str(end))
            self.budget.output += len(text)
            if self.budget.output <= MAX_OUTPUT:
                self.output(text)

        def b_fail(message="skill failed"):
            raise SandboxError(safe_str(message))

        def type_name(value):
            return {type(None): "none", bool: "bool", int: "int", float: "float", str: "str", list: "list",
                    tuple: "tuple", dict: "dict", set: "set", range: "range"}.get(type(value), "function")

        plain = {
            "abs": abs, "all": all, "any": any, "bool": bool, "divmod": divmod, "float": float, "int": b_int,
            "len": len, "round": round, "chr": chr, "ord": ord, "str": safe_str, "repr": safe_repr,
            "list": lambda x=(): _size_ok(list(x)), "tuple": lambda x=(): _size_ok(tuple(x)),
            "dict": lambda *a, **k: _size_ok(dict(*a, **k)), "set": lambda x=(): _size_ok(set(x)),
            "enumerate": lambda x, start=0: list(enumerate(x, start)), "zip": lambda *x: list(zip(*x)),
            "reversed": lambda x: list(reversed(x)), "range": b_range, "sum": b_sum,
            "sorted": b_sorted, "max": b_max, "min": b_min, "print": b_print, "fail": b_fail,
            "type_name": type_name, "floor": math.floor, "ceil": math.ceil, "sqrt": math.sqrt,
            "hypot": math.hypot, "atan2": math.atan2, "dist": math.dist, "isclose": math.isclose,
        }
        out = {name: HostFunction(name, fn, raw=True) for name, fn in plain.items()}
        out["pi"] = math.pi
        out["True"], out["False"], out["None"] = True, False, None
        return out

    # -- statements
    def _step(self, node):
        b = self.budget
        b.steps += 1
        if b.steps & 2047 == 0:
            b.check()
        elif b.steps > b.max_steps:
            b.check()

    def _err(self, node, message):
        return SandboxError(f"{self.filename}: line {getattr(node, 'lineno', '?')}: {message}")

    def _block(self, body, scopes):
        for stmt in body:
            self._stmt(stmt, scopes)

    def _stmt(self, node, scopes):
        self._step(node)
        kind = type(node)
        try:
            if kind is ast.Expr:
                self._expr(node.value, scopes)
            elif kind is ast.Assign:
                value = self._expr(node.value, scopes)
                for target in node.targets:
                    self._assign(target, value, scopes)
            elif kind is ast.AugAssign:
                current = self._expr(_as_load(node.target), scopes)
                value = self._binop(node.op, current, self._expr(node.value, scopes), node)
                self._assign(node.target, value, scopes)
            elif kind is ast.If:
                self._block(node.body if self._truth(self._expr(node.test, scopes)) else node.orelse, scopes)
            elif kind is ast.For:
                broke = False
                for item in self._iter(self._expr(node.iter, scopes), node):
                    self._assign(node.target, item, scopes)
                    try:
                        self._block(node.body, scopes)
                    except _Continue:
                        continue
                    except _Break:
                        broke = True
                        break
                if not broke:
                    self._block(node.orelse, scopes)
            elif kind is ast.While:
                broke = False
                while self._truth(self._expr(node.test, scopes)):
                    self._step(node)
                    try:
                        self._block(node.body, scopes)
                    except _Continue:
                        continue
                    except _Break:
                        broke = True
                        break
                if not broke:
                    self._block(node.orelse, scopes)
            elif kind is ast.FunctionDef:
                scopes[0][node.name] = self._make_function(node.name, node, scopes)
            elif kind is ast.Return:
                raise _Return(self._expr(node.value, scopes) if node.value else None)
            elif kind is ast.Break:
                raise _Break()
            elif kind is ast.Continue:
                raise _Continue()
            elif kind is ast.Pass:
                pass
            elif kind is ast.Assert:
                if not self._truth(self._expr(node.test, scopes)):
                    message = safe_str(self._expr(node.msg, scopes)) if node.msg else "assertion failed"
                    raise self._err(node, message)
            else:
                raise self._err(node, f"{kind.__name__} is not allowed")
        except (SandboxError, _Break, _Continue, _Return):
            raise
        except RecursionError:
            raise self._err(node, "nested too deeply") from None
        except Exception as err:     # ordinary errors in the script: KeyError, TypeError, ZeroDivisionError...
            raise self._err(node, f"{type(err).__name__}: {err}") from None

    def _make_function(self, name, node, scopes, is_lambda=False):
        args = node.args
        defaults = [self._expr(d, scopes) for d in args.defaults]
        kw_defaults = [self._expr(d, scopes) if d is not None else _MISSING for d in args.kw_defaults]
        return Function(name, node, defaults, kw_defaults, list(scopes), self, is_lambda)

    def _assign(self, target, value, scopes):
        kind = type(target)
        if kind is ast.Name:
            scopes[0][target.id] = value
        elif kind in (ast.Tuple, ast.List):
            items = list(self._iter(value, target))
            starred = [i for i, t in enumerate(target.elts) if isinstance(t, ast.Starred)]
            if starred:
                at = starred[0]
                after = len(target.elts) - at - 1
                if len(items) < len(target.elts) - 1:
                    raise self._err(target, "not enough values to unpack")
                head, middle, tail = items[:at], items[at:len(items) - after], items[len(items) - after:]
                for t, v in zip(target.elts[:at], head):
                    self._assign(t, v, scopes)
                self._assign(target.elts[at].value, list(middle), scopes)
                for t, v in zip(target.elts[at + 1:], tail):
                    self._assign(t, v, scopes)
            else:
                if len(items) != len(target.elts):
                    raise self._err(target, f"expected {len(target.elts)} values to unpack, got {len(items)}")
                for t, v in zip(target.elts, items):
                    self._assign(t, v, scopes)
        elif kind is ast.Subscript:
            container = self._expr(target.value, scopes)
            if not isinstance(container, (list, dict)):
                raise self._err(target, f"cannot assign into a {type(container).__name__}")
            key = self._expr(target.slice, scopes)
            container[key] = value
            _size_ok(container)
        else:
            raise self._err(target, "cannot assign to that")

    # -- expressions
    def _truth(self, value):
        return bool(value)

    def _iter(self, value, node):
        if isinstance(value, (list, tuple, str, range)):
            return value
        if isinstance(value, (dict, set)):
            return list(value)
        raise self._err(node, f"cannot iterate over a {type(value).__name__}")

    def _lookup(self, name, scopes, node):
        for scope in scopes:
            if name in scope:
                return scope[name]
        if name in self.globals:
            return self.globals[name]
        if name in self.builtins:
            return self.builtins[name]
        raise self._err(node, f"name {name!r} is not defined")

    def _expr(self, node, scopes):
        self._step(node)
        kind = type(node)
        if kind is ast.Constant:
            return node.value
        if kind is ast.Name:
            return self._lookup(node.id, scopes, node)
        if kind is ast.BinOp:
            return self._binop(node.op, self._expr(node.left, scopes), self._expr(node.right, scopes), node)
        if kind is ast.Compare:
            left = self._expr(node.left, scopes)
            for op, right_node in zip(node.ops, node.comparators):
                right = self._expr(right_node, scopes)
                if not _compare(op, left, right):
                    return False
                left = right
            return True
        if kind is ast.BoolOp:
            if isinstance(node.op, ast.And):
                value = True
                for sub in node.values:
                    value = self._expr(sub, scopes)
                    if not value:
                        return value
                return value
            value = False
            for sub in node.values:
                value = self._expr(sub, scopes)
                if value:
                    return value
            return value
        if kind is ast.UnaryOp:
            value = self._expr(node.operand, scopes)
            op = type(node.op)
            if op is ast.Not:
                return not value
            if op is ast.USub:
                return -value
            if op is ast.UAdd:
                return +value
            if op is ast.Invert:
                return ~value
        if kind is ast.IfExp:
            return self._expr(node.body if self._truth(self._expr(node.test, scopes)) else node.orelse, scopes)
        if kind is ast.Call:
            return self._call_node(node, scopes)
        if kind is ast.Subscript:
            container = self._expr(node.value, scopes)
            key = self._expr(node.slice, scopes)
            if not isinstance(container, (list, tuple, dict, str, range)):
                raise self._err(node, f"cannot index a {type(container).__name__}")
            return _size_ok(container[key])
        if kind is ast.Slice:
            return slice(*(self._expr(p, scopes) if p is not None else None for p in (node.lower, node.upper, node.step)))
        if kind is ast.List:
            return _size_ok(self._elements(node.elts, scopes))
        if kind is ast.Tuple:
            return tuple(self._elements(node.elts, scopes))
        if kind is ast.Set:
            return _size_ok(set(self._elements(node.elts, scopes)))
        if kind is ast.Dict:
            out = {}
            for k, v in zip(node.keys, node.values):
                if k is None:
                    extra = self._expr(v, scopes)
                    if not isinstance(extra, dict):
                        raise self._err(node, "** needs a dict")
                    out.update(extra)
                else:
                    out[self._expr(k, scopes)] = self._expr(v, scopes)
            return _size_ok(out)
        if kind in (ast.ListComp, ast.SetComp, ast.GeneratorExp, ast.DictComp):
            return self._comprehension(node, scopes)
        if kind is ast.Lambda:
            return self._make_function("lambda", node, scopes, is_lambda=True)
        if kind is ast.JoinedStr:
            parts = []
            for value in node.values:
                parts.append(self._expr(value, scopes))
            return _size_ok("".join(parts))
        if kind is ast.FormattedValue:
            value = self._expr(node.value, scopes)
            if node.conversion == ord("r") or node.conversion == ord("a"):
                value = safe_repr(value)
            elif node.conversion == ord("s"):
                value = safe_str(value)
            spec = self._expr(node.format_spec, scopes) if node.format_spec else ""
            _check_format_spec(spec)
            if not isinstance(value, (int, float, str, bool, type(None))):
                value = safe_repr(value)
            return format(value, spec) if spec else safe_str(value)
        if kind is ast.Attribute:
            raise self._err(node, "attributes can only be called")
        if kind is ast.Starred:
            raise self._err(node, "* is only allowed in calls and unpacking")
        raise self._err(node, f"{kind.__name__} is not allowed")

    def _elements(self, elts, scopes):
        out = []
        for e in elts:
            if isinstance(e, ast.Starred):
                out.extend(self._iter(self._expr(e.value, scopes), e))
            else:
                out.append(self._expr(e, scopes))
        return out

    def _comprehension(self, node, scopes):
        scope = {}
        inner = [scope] + scopes
        results = [] if not isinstance(node, ast.DictComp) else {}

        def loop(index):
            if index == len(node.generators):
                if isinstance(node, ast.DictComp):
                    results[self._expr(node.key, inner)] = self._expr(node.value, inner)
                else:
                    results.append(self._expr(node.elt, inner))
                if len(results) > MAX_LEN:
                    raise self._err(node, "comprehension too large")
                return
            gen = node.generators[index]
            source = self._expr(gen.iter, inner if index else scopes)
            for item in self._iter(source, gen):
                self._step(gen)
                self._assign(gen.target, item, inner)
                if all(self._truth(self._expr(cond, inner)) for cond in gen.ifs):
                    loop(index + 1)

        loop(0)
        if isinstance(node, ast.SetComp):
            return set(results)
        return results

    def _binop(self, op, left, right, node):
        kind = type(op)
        seq = (str, list, tuple)
        if kind is ast.Add:
            if isinstance(left, seq) and isinstance(right, seq) and len(left) + len(right) > MAX_LEN:
                raise self._err(node, "result too large")
            return _size_ok(left + right)
        if kind is ast.Mult:
            for a, b in ((left, right), (right, left)):
                if isinstance(a, seq) and isinstance(b, int) and len(a) * max(b, 0) > MAX_LEN:
                    raise self._err(node, "result too large")
            return _size_ok(left * right)
        if kind is ast.Pow:
            if isinstance(left, int) and isinstance(right, int) and right > 0 and abs(left) > 1:
                if right * left.bit_length() > MAX_INT_BITS:
                    raise self._err(node, "result too large")
            return _size_ok(left ** right)
        if kind is ast.LShift:
            if isinstance(right, int) and right > MAX_INT_BITS:
                raise self._err(node, "shift too large")
            return _size_ok(left << right)
        if kind is ast.Mod and isinstance(left, str):
            raise self._err(node, "use f-strings instead of % formatting")
        fn = {ast.Sub: lambda a, b: a - b, ast.Div: lambda a, b: a / b, ast.FloorDiv: lambda a, b: a // b,
              ast.Mod: lambda a, b: a % b, ast.RShift: lambda a, b: a >> b, ast.BitAnd: lambda a, b: a & b,
              ast.BitOr: lambda a, b: a | b, ast.BitXor: lambda a, b: a ^ b}.get(kind)
        if fn is None:
            raise self._err(node, f"{kind.__name__} is not allowed")
        return _size_ok(fn(left, right))

    def _call_node(self, node, scopes):
        args = []
        for a in node.args:
            if isinstance(a, ast.Starred):
                args.extend(self._iter(self._expr(a.value, scopes), a))
            else:
                args.append(self._expr(a, scopes))
        kwargs = {}
        for k in node.keywords:
            if k.arg is None:
                extra = self._expr(k.value, scopes)
                if not isinstance(extra, dict) or not all(isinstance(key, str) and not key.startswith("_") for key in extra):
                    raise self._err(node, "** needs a dict with plain string keys")
                kwargs.update(extra)
            else:
                kwargs[k.arg] = self._expr(k.value, scopes)
        func = node.func
        if isinstance(func, ast.Attribute):
            receiver = self._expr(func.value, scopes)
            return self._method(receiver, func.attr, args, kwargs, node)
        target = self._expr(func, scopes)
        return self._call(target, args, kwargs, getattr(node, "lineno", 0), node)

    def _method(self, receiver, name, args, kwargs, node):
        allowed = METHODS.get(type(receiver))
        if not allowed or name not in allowed:
            raise self._err(node, f"{type(receiver).__name__} has no allowed method .{name}")
        if isinstance(receiver, str):
            if name == "replace":
                old, new = args[0], args[1]
                count = receiver.count(old) if old else len(receiver) + 1
                if len(args) > 2 and isinstance(args[2], int) and args[2] >= 0:
                    count = min(count, args[2])
                if len(receiver) + count * (len(new) - len(old)) > MAX_LEN:
                    raise self._err(node, "result too large")
            elif name == "join":
                items = list(args[0])
                if not all(isinstance(i, str) for i in items):
                    raise self._err(node, "join() needs strings")
                if sum(map(len, items)) + len(receiver) * max(len(items) - 1, 0) > MAX_LEN:
                    raise self._err(node, "result too large")
                args = [items]
        if name in ("extend", "update") and args and hasattr(args[0], "__len__") and len(receiver) + len(args[0]) > MAX_LEN:
            raise self._err(node, "result too large")
        if name == "sort":
            key = kwargs.get("key")
            if key is not None:
                kwargs["key"] = lambda v: self._call(key, [v], {}, 0)
        result = getattr(receiver, name)(*args, **kwargs)
        _size_ok(receiver)
        if name in ("keys", "values", "items"):
            return list(result)
        return _size_ok(result)

    def _call(self, fn, args, kwargs, lineno, node=None):
        b = self.budget
        if isinstance(fn, HostFunction):
            if fn.raw:
                return _size_ok(fn.fn(*args, **kwargs))
            started = time.process_time()
            try:
                result = fn.fn(*[_plain(a) for a in args], **{k: _plain(v) for k, v in kwargs.items()})
            except SandboxError:
                raise
            except Exception as err:
                raise SandboxError(f"{self.filename}: line {lineno}: {fn.name}: {err}") from None
            finally:
                b.host_cpu += time.process_time() - started
            b.check()
            return sanitize(result)
        if not isinstance(fn, Function):
            raise SandboxError(f"{self.filename}: line {lineno}: {type(fn).__name__} is not callable")
        if b.depth >= MAX_DEPTH:
            raise SandboxError(f"{self.filename}: line {lineno}: calls nested more than {MAX_DEPTH} deep")
        scope = fn.interp._bind(fn, args, kwargs, lineno)
        b.depth += 1
        try:
            if fn.is_lambda:
                return fn.interp._expr(fn.node.body, [scope] + fn.scopes)
            try:
                fn.interp._block(fn.node.body, [scope] + fn.scopes)
            except _Return as ret:
                return ret.value
            except (_Break, _Continue):
                raise SandboxError(f"{self.filename}: break/continue outside a loop in {fn.name}") from None
            return None
        finally:
            b.depth -= 1

    def _bind(self, fn, args, kwargs, lineno):
        a = fn.node.args
        params = [p.arg for p in a.posonlyargs + a.args]
        scope = {}
        if len(args) > len(params) and not a.vararg:
            raise SandboxError(f"{self.filename}: line {lineno}: {fn.name}() takes {len(params)} positional arguments, got {len(args)}")
        for name, value in zip(params, args):
            scope[name] = value
        if a.vararg:
            scope[a.vararg.arg] = list(args[len(params):])
        kwonly = [p.arg for p in a.kwonlyargs]
        rest = {}
        for key, value in kwargs.items():
            if key in params or key in kwonly:
                if key in scope:
                    raise SandboxError(f"{self.filename}: line {lineno}: {fn.name}() got {key!r} twice")
                scope[key] = value
            elif a.kwarg:
                rest[key] = value
            else:
                raise SandboxError(f"{self.filename}: line {lineno}: {fn.name}() got an unexpected argument {key!r}")
        first_default = len(params) - len(fn.defaults)
        for index, name in enumerate(params):
            if name not in scope:
                if index >= first_default:
                    scope[name] = fn.defaults[index - first_default]
                else:
                    raise SandboxError(f"{self.filename}: line {lineno}: {fn.name}() is missing argument {name!r}")
        for name, default in zip(kwonly, fn.kw_defaults):
            if name not in scope:
                if default is _MISSING:
                    raise SandboxError(f"{self.filename}: line {lineno}: {fn.name}() is missing argument {name!r}")
                scope[name] = default
        if a.kwarg:
            scope[a.kwarg.arg] = rest
        return scope


_MISSING = object()


def _as_load(target):
    if isinstance(target, ast.Name):
        return ast.copy_location(ast.Name(id=target.id, ctx=ast.Load()), target)
    if isinstance(target, ast.Subscript):
        return ast.copy_location(ast.Subscript(value=target.value, slice=target.slice, ctx=ast.Load()), target)
    raise SandboxError("cannot use that with an augmented assignment")


def _compare(op, a, b):
    kind = type(op)
    if kind is ast.Eq:
        return a == b
    if kind is ast.NotEq:
        return a != b
    if kind is ast.Lt:
        return a < b
    if kind is ast.LtE:
        return a <= b
    if kind is ast.Gt:
        return a > b
    if kind is ast.GtE:
        return a >= b
    if kind is ast.In:
        return a in b
    if kind is ast.NotIn:
        return a not in b
    if kind is ast.Is:
        return a is b
    if kind is ast.IsNot:
        return a is not b
    raise SandboxError(f"{kind.__name__} is not allowed")
