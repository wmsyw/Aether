"""
FormulaEngine - 配置驱动的安全计费表达式引擎

目标：
- 支持 billing_rules.expression 的安全求值（AST 白名单）
- 支持 dimension_mappings（dimension/matrix/tiered/constant）
- 支持 required/allow_zero 机制，避免维度缺失导致静默少收

注意：该模块不直接依赖数据库；规则查找、维度采集在上层服务完成。
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from typing import Any, Iterable, Literal


class UnsafeExpressionError(ValueError):
    """表达式包含不安全/不支持的 AST 结构。"""


class ExpressionEvaluationError(RuntimeError):
    """表达式在安全求值阶段失败（如 NameError/ZeroDivision）。"""


class BillingIncompleteError(RuntimeError):
    """required 维度缺失且 strict_mode=true 时抛出，用于上层拒绝请求/标记任务失败。"""

    def __init__(self, message: str, *, missing_required: list[str]):
        super().__init__(message)
        self.missing_required = missing_required


@dataclass(frozen=True)
class FormulaEvaluationResult:
    status: Literal["complete", "incomplete"]
    cost: float
    resolved_values: dict[str, Any]
    missing_required: list[str]
    error: str | None = None


_ALLOWED_BINOPS = (
    ast.Add,
    ast.Sub,
    ast.Mult,
    ast.Div,
    ast.Pow,
    ast.FloorDiv,
    ast.Mod,
)
_ALLOWED_UNARYOPS = (ast.UAdd, ast.USub)
_ALLOWED_OP_NODES = _ALLOWED_BINOPS + _ALLOWED_UNARYOPS


def _iter_ast_nodes(node: ast.AST) -> Iterable[ast.AST]:
    yield node
    for child in ast.iter_child_nodes(node):
        yield from _iter_ast_nodes(child)


def extract_variable_names(expression: str) -> set[str]:
    """提取表达式中出现的变量名（不含函数名）。"""
    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError as exc:
        raise UnsafeExpressionError(f"Invalid expression syntax: {exc}") from exc

    names: set[str] = set()
    for node in _iter_ast_nodes(tree):
        if isinstance(node, ast.Name):
            names.add(node.id)
        if isinstance(node, ast.Call):
            # Call 的函数名会以 ast.Name 出现，需要从结果中过滤掉
            if isinstance(node.func, ast.Name):
                names.discard(node.func.id)
    return names


class SafeExpressionEvaluator:
    """AST 白名单 + 无 builtins 的安全求值器。"""

    ALLOWED_FUNCS: dict[str, Any] = {
        "min": min,
        "max": max,
        "abs": abs,
        "round": round,
        "int": int,
        "float": float,
    }

    def validate(self, expression: str) -> ast.Expression:
        try:
            tree = ast.parse(expression, mode="eval")
        except SyntaxError as exc:
            raise UnsafeExpressionError(f"Invalid expression syntax: {exc}") from exc

        for node in _iter_ast_nodes(tree):
            if isinstance(node, ast.Expression):
                continue
            # 运算符节点本身也会出现在 iter_child_nodes 中
            if isinstance(node, _ALLOWED_OP_NODES):
                continue
            if isinstance(node, ast.Constant):
                # 仅允许数字常量（bool 是 int 子类，需要显式排除）
                if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
                    raise UnsafeExpressionError("Only int/float constants are allowed")
                continue
            if isinstance(node, ast.BinOp):
                if not isinstance(node.op, _ALLOWED_BINOPS):
                    raise UnsafeExpressionError(f"Operator not allowed: {type(node.op).__name__}")
                continue
            if isinstance(node, ast.UnaryOp):
                if not isinstance(node.op, _ALLOWED_UNARYOPS):
                    raise UnsafeExpressionError(
                        f"Unary operator not allowed: {type(node.op).__name__}"
                    )
                continue
            if isinstance(node, ast.Name):
                # 防御：拒绝双下划线变量名
                if node.id.startswith("__"):
                    raise UnsafeExpressionError("Dunder names are not allowed")
                continue
            if isinstance(node, ast.Load):
                continue
            if isinstance(node, ast.keyword):
                continue
            if isinstance(node, ast.Call):
                if not isinstance(node.func, ast.Name):
                    raise UnsafeExpressionError("Only direct function calls are allowed")
                func_name = node.func.id
                if func_name not in self.ALLOWED_FUNCS:
                    raise UnsafeExpressionError(f"Function not allowed: {func_name}")
                if any(k.arg is None for k in node.keywords):
                    raise UnsafeExpressionError("**kwargs is not allowed")
                continue

            # 明确禁止的/不需要的节点类型（属性访问、下标、推导式、比较等）
            if isinstance(
                node,
                (
                    ast.Attribute,
                    ast.Subscript,
                    ast.Compare,
                    ast.BoolOp,
                    ast.IfExp,
                    ast.Lambda,
                    ast.Dict,
                    ast.List,
                    ast.Tuple,
                    ast.Set,
                    ast.ListComp,
                    ast.SetComp,
                    ast.DictComp,
                    ast.GeneratorExp,
                    ast.Await,
                    ast.Yield,
                    ast.YieldFrom,
                ),
            ):
                raise UnsafeExpressionError(f"AST node not allowed: {type(node).__name__}")

            raise UnsafeExpressionError(f"AST node not allowed: {type(node).__name__}")

        assert isinstance(tree, ast.Expression)
        return tree

    def eval_number(self, expression: str, variables: dict[str, Any]) -> float:
        tree = self.validate(expression)

        safe_globals = {"__builtins__": {}}
        safe_locals = dict(self.ALLOWED_FUNCS)
        safe_locals.update(variables or {})

        try:
            compiled = compile(tree, "<billing_expr>", "eval")
            value = eval(compiled, safe_globals, safe_locals)  # noqa: S307 - validated AST
        except Exception as exc:
            raise ExpressionEvaluationError(str(exc)) from exc

        try:
            return float(value)
        except Exception as exc:
            raise ExpressionEvaluationError(f"Expression result is not numeric: {value!r}") from exc


class FormulaEngine:
    """计费表达式引擎：解析 dimension_mappings 并进行安全求值。"""

    def __init__(self) -> None:
        self._evaluator = SafeExpressionEvaluator()

    def evaluate(
        self,
        *,
        expression: str,
        variables: dict[str, Any] | None,
        dimensions: dict[str, Any] | None,
        dimension_mappings: dict[str, dict[str, Any]] | None,
        strict_mode: bool = False,
    ) -> FormulaEvaluationResult:
        dims = dimensions or {}
        mappings = dimension_mappings or {}
        resolved: dict[str, Any] = dict(variables or {})

        missing_required: list[str] = []

        # 先解析 dimension_mappings，产出 expression 变量表
        for var_name, mapping in mappings.items():
            source = (mapping.get("source") or "constant").lower()
            # 显式 constant 映射属于“兜底行为”：如果 variables 已经提供该变量，则不覆盖。
            if source == "constant" and var_name in resolved:
                continue
            value, is_missing = self._resolve_mapping(var_name, mapping, dims)
            if is_missing:
                missing_required.append(var_name)
                continue
            resolved[var_name] = value

        # required 维度缺失：直接标记 incomplete（并由 strict_mode 决定是否抛错）
        if missing_required:
            if strict_mode:
                raise BillingIncompleteError(
                    f"Missing required dimensions: {missing_required}",
                    missing_required=missing_required,
                )
            return FormulaEvaluationResult(
                status="incomplete",
                cost=0.0,
                resolved_values=resolved,
                missing_required=missing_required,
            )

        try:
            cost = self._evaluator.eval_number(expression, resolved)
            if cost < 0:
                # 防御：不允许负数成本（通常表示配置错误）
                return FormulaEvaluationResult(
                    status="incomplete",
                    cost=0.0,
                    resolved_values=resolved,
                    missing_required=[],
                    error="negative_cost",
                )
            return FormulaEvaluationResult(
                status="complete",
                cost=cost,
                resolved_values=resolved,
                missing_required=[],
            )
        except (UnsafeExpressionError, ExpressionEvaluationError) as exc:
            if strict_mode:
                raise
            return FormulaEvaluationResult(
                status="incomplete",
                cost=0.0,
                resolved_values=resolved,
                missing_required=[],
                error=str(exc),
            )

    def _resolve_mapping(
        self,
        var_name: str,
        mapping: dict[str, Any],
        dims: dict[str, Any],
    ) -> tuple[Any, bool]:
        """
        Returns:
            (value, is_missing_required)

        说明：
        - is_missing_required 仅在 required=true 且缺失时为 True
        - required=false 的缺失会使用 default 或 0 兜底，并返回 is_missing_required=False
        """
        source = (mapping.get("source") or "constant").lower()
        required = bool(mapping.get("required", False))
        allow_zero = bool(mapping.get("allow_zero", False))

        default = mapping.get("default", 0)

        def _missing() -> tuple[Any, bool]:
            if required:
                return None, True
            return default, False

        if source == "constant":
            # constant 默认行为：由 variables 提供；dimension_mappings 显式 constant 时仅做兜底
            return default, False

        if source == "dimension":
            key = mapping.get("key") or var_name
            raw = dims.get(key)
            if raw is None:
                return _missing()
            if isinstance(raw, str):
                if raw == "":
                    return _missing()
                # 尝试将字符串解析为数字，否则按字符串返回（供上层自行决定）
                try:
                    num = float(raw)
                    if num == 0 and not allow_zero:
                        return _missing()
                    return num, False
                except Exception:
                    return raw, False
            if isinstance(raw, (int, float)):
                if float(raw) == 0 and not allow_zero:
                    return _missing()
                return raw, False
            # 其他类型：尽量转为 float，否则视为缺失
            try:
                num = float(raw)
                if num == 0 and not allow_zero:
                    return _missing()
                return num, False
            except Exception:
                return _missing()

        if source == "matrix":
            key = mapping.get("key") or var_name
            raw = dims.get(key)
            if raw is None or raw == "":
                return _missing()
            raw_key = str(raw)
            matrix = mapping.get("map") or {}
            if raw_key in matrix:
                return matrix[raw_key], False
            # matrix 未命中：若 required=true 则仍视为缺失；否则使用 default
            if required:
                return None, True
            return default, False

        if source == "tiered":
            tier_key = mapping.get("tier_key")
            if not tier_key:
                return _missing()
            raw_tier_value = dims.get(tier_key)
            if raw_tier_value is None:
                return _missing()
            try:
                tier_value = float(raw_tier_value)
            except Exception:
                return _missing()

            if tier_value == 0 and not allow_zero:
                return _missing()

            tiers = mapping.get("tiers") or []
            # tiers: [{up_to: 128000, value: 2.5}, {up_to: null, value: 1.25}]
            for tier in tiers:
                up_to = tier.get("up_to")
                if up_to is None:
                    return tier.get("value", default), False
                try:
                    if tier_value <= float(up_to):
                        return tier.get("value", default), False
                except Exception:
                    # up_to 配置异常：忽略并继续
                    continue
            # 无匹配：使用最后一个或 default
            if tiers:
                return tiers[-1].get("value", default), False
            return default, False

        # 未知 source：视为配置错误，但不直接中断计费（返回 default）
        return default, False
