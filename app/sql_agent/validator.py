"""AST-based SQL safety validator using sqlglot (PostgreSQL dialect)."""
from __future__ import annotations

import re

import sqlglot
from sqlglot import TokenType, exp

from app.gateway.exceptions import SQLRejected
from app.sql_agent.schema_prompt import ALLOWLISTED_VIEWS

MAX_SQL_LIMIT = 200
_ALLOWLIST_SET = frozenset(ALLOWLISTED_VIEWS)
_FORBIDDEN_NAMESPACES = frozenset({"information_schema", "pg_catalog"})

BLOCKED_FUNCTIONS = frozenset({
    "pg_sleep",
    "pg_read_file",
    "pg_ls_dir",
    "lo_import",
    "lo_export",
    "dblink",
    "copy",
    "set_config",
    "current_setting",
    "pg_terminate_backend",
})

_DANGEROUS_COMMENT_RE = re.compile(r"(;|INTO\b|FOR\s+UPDATE\b|\bLOCK\b)", re.IGNORECASE)
_FOR_UPDATE_RE = re.compile(r"\bFOR\s+UPDATE\b", re.IGNORECASE)

_FORBIDDEN_NODE_NAMES = (
    "Insert",
    "Update",
    "Delete",
    "Drop",
    "Create",
    "Alter",
    "Command",
    "Merge",
    "Copy",
    "Lock",
    "Into",
    "Set",
    "Transaction",
    "Commit",
    "Rollback",
    "Grant",
    "Revoke",
    "TruncateTable",
)
_FORBIDDEN_NODE_TYPES = tuple(
    cls for name in _FORBIDDEN_NODE_NAMES if (cls := getattr(exp, name, None)) is not None
)


def _check_comments_and_tokens(sql: str) -> None:
    """Reject comments containing ';', INTO, FOR UPDATE, or LOCK, and dangerous keywords."""
    try:
        tokens = sqlglot.tokenize(sql, read="postgres")
    except Exception as exc:
        raise SQLRejected(f"SQL tokenization failed: {exc}") from exc

    for idx, tok in enumerate(tokens):
        for comment in tok.comments or ():
            if ";" in comment or _DANGEROUS_COMMENT_RE.search(comment):
                raise SQLRejected("SQL comments cannot contain ';', INTO, FOR UPDATE, or LOCK.")

        if tok.token_type in (TokenType.INTO, TokenType.LOCK):
            raise SQLRejected(f"Disallowed SQL keyword '{tok.text}' detected.")

        if (
            tok.token_type == TokenType.FOR
            and idx + 1 < len(tokens)
            and tokens[idx + 1].token_type == TokenType.UPDATE
        ):
            raise SQLRejected("FOR UPDATE clause is not allowed.")


def _extract_func_name(func: exp.Func) -> str:
    if isinstance(func, exp.Anonymous):
        return str(func.this or "").strip().lower()
    return (func.sql_name() or "").strip().lower()


def _enforce_limit(ast: exp.Select) -> exp.Select:
    """Ensure top-level SELECT has LIMIT <= 200 (adding LIMIT 200 if absent)."""
    limit_node = ast.args.get("limit")
    if limit_node is None:
        return ast.limit(MAX_SQL_LIMIT)

    if isinstance(limit_node, exp.Fetch):
        count_expr = limit_node.args.get("count")
        if (
            isinstance(count_expr, exp.Literal)
            and not count_expr.is_string
            and str(count_expr.this).isdigit()
        ):
            val = int(count_expr.this)
            if 1 <= val <= MAX_SQL_LIMIT:
                return ast
        ast.set("limit", None)
        return ast.limit(MAX_SQL_LIMIT)

    if isinstance(limit_node, exp.Limit):
        expr = limit_node.expression
        if (
            isinstance(expr, exp.Literal)
            and not expr.is_string
            and str(expr.this).isdigit()
        ):
            val = int(expr.this)
            if 1 <= val <= MAX_SQL_LIMIT:
                return ast
        ast.set("limit", None)
        return ast.limit(MAX_SQL_LIMIT)

    ast.set("limit", None)
    return ast.limit(MAX_SQL_LIMIT)


def validate_sql(sql: str) -> str:
    """Parse, validate, and normalize PostgreSQL query per SECURITY.md section 4.

    Raises:
        SQLRejected: If the query violates any safety rule.
    Returns:
        Normalized PostgreSQL SELECT string with LIMIT <= 200.
    """
    if not sql or not sql.strip():
        raise SQLRejected("SQL query cannot be empty.")

    _check_comments_and_tokens(sql)

    try:
        statements = sqlglot.parse(sql, read="postgres")
    except Exception as exc:
        raise SQLRejected(f"Invalid SQL syntax: {exc}") from exc

    if len(statements) != 1 or statements[0] is None:
        raise SQLRejected("Exactly one SQL statement is required.")

    ast = statements[0]

    # Walk AST comments as well
    for node in ast.walk():
        for comment in getattr(node, "comments", None) or ():
            if ";" in comment or _DANGEROUS_COMMENT_RE.search(comment):
                raise SQLRejected("SQL comments cannot contain ';', INTO, FOR UPDATE, or LOCK.")

        if isinstance(node, _FORBIDDEN_NODE_TYPES):
            raise SQLRejected(f"Disallowed SQL construct '{type(node).__name__}'.")

        if isinstance(node, exp.Dot):
            dot_text = node.sql(dialect="postgres").lower()
            if any(ns in dot_text for ns in _FORBIDDEN_NAMESPACES) or any(
                isinstance(part, exp.Func) for part in (node.this, node.expression)
            ):
                raise SQLRejected("Schema-qualified expressions and system catalogs are forbidden.")

    # Rule 2: Root must be exp.Select
    if not isinstance(ast, exp.Select):
        raise SQLRejected("Only SELECT statements are allowed.")

    # Reject FOR UPDATE / INTO phrases if not caught by AST
    if _FOR_UPDATE_RE.search(ast.sql(dialect="postgres")):
        raise SQLRejected("FOR UPDATE clause is not allowed.")

    # Rule 3: Collect CTE names and verify all referenced tables are in allowlist
    cte_names = {
        cte.alias_or_name.strip().lower()
        for cte in ast.find_all(exp.CTE)
        if cte.alias_or_name
    }

    for table in ast.find_all(exp.Table):
        if table.catalog or table.db:
            tbl_sql = table.sql(dialect="postgres")
            raise SQLRejected(
                f"Schema-qualified table references are forbidden: '{tbl_sql}'."
            )
        tname = (table.name or "").strip().lower()
        if not tname or tname in _FORBIDDEN_NAMESPACES:
            raise SQLRejected(f"Forbidden table or namespace: '{tname}'.")
        if tname not in _ALLOWLIST_SET and tname not in cte_names:
            raise SQLRejected(f"Table '{tname}' is not in the SQL view allowlist.")

    # Rule 4: Blocked functions and any pg_* function
    for func in ast.find_all(exp.Func):
        fname = _extract_func_name(func)
        if fname in BLOCKED_FUNCTIONS or fname.startswith("pg_"):
            raise SQLRejected(f"Function '{fname}' is not allowed.")

    # Rule 6: Enforce LIMIT <= 200
    limited_ast = _enforce_limit(ast)
    return limited_ast.sql(dialect="postgres")
