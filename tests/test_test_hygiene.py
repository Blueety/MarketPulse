"""测试套件自检（BUG-016 元测试）：同一文件内不得重复定义同名 `test_*` 函数。

Python 里后定义遮蔽前定义 ⇒ 被遮蔽的那份**永不执行**，而 pytest 依旧全绿：`tests/test_backtest.py`
曾有两组一模一样的「搬迁护栏」用例（137/162 与 177/202 行），前一组从来没跑过，「774 passed」
因此是假象。

用 `ast` 解析而不是正则：正则会把注释/字符串里的 `def test_x` 也算成定义。
作用域参与比较（模块级 / 同类内）—— 不同类里各有一个同名用例是合法的，同作用域重名才是遮蔽。
"""
import ast
from collections import defaultdict
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent

#: 需要下钻的可嵌套语句块（`def`/`class` 单独处理：函数体内的嵌套 def 不被 pytest 收集）。
_BLOCK_HOLDERS = (ast.If, ast.For, ast.While, ast.With, ast.AsyncFor, ast.AsyncWith)


def _child_bodies(stmt):
    """一条复合语句直接包含的语句块（`if/for/...`: body+orelse；`try`: 含 handlers/finalbody）。"""
    if isinstance(stmt, ast.Try):
        return [stmt.body, stmt.orelse, stmt.finalbody] + [h.body for h in stmt.handlers]
    return [b for b in (getattr(stmt, "body", None), getattr(stmt, "orelse", None)) if b]


def _test_defs(body, scope=()):
    """产出 `(作用域, 函数名, 行号)`；作用域为类名元组（模块级 = 空元组）。"""
    for stmt in body:
        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if stmt.name.startswith("test_"):
                yield scope, stmt.name, stmt.lineno
        elif isinstance(stmt, ast.ClassDef):
            yield from _test_defs(stmt.body, scope + (stmt.name,))
        elif isinstance(stmt, _BLOCK_HOLDERS):
            for block in _child_bodies(stmt):
                yield from _test_defs(block, scope)


def test_no_duplicate_test_function_names_in_a_file():
    files = sorted(TESTS_DIR.glob("*.py"))
    assert files, "tests/ 下一个 .py 都没扫到 —— 空集不算过"
    dupes = []
    for path in files:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        seen = defaultdict(list)
        for scope, name, lineno in _test_defs(tree.body):
            seen[(scope, name)].append(lineno)
        for (scope, name), linenos in sorted(seen.items()):
            if len(linenos) > 1:
                qualname = ".".join(scope + (name,))
                dupes.append("%s::%s 定义了 %d 次（行 %s）—— 后定义遮蔽前者，前面那份永不执行"
                             % (path.name, qualname, len(linenos), "、".join(map(str, linenos))))
    assert not dupes, "同一文件内重复定义同名 test_*：\n" + "\n".join(dupes)
