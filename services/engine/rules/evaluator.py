from __future__ import annotations

from typing import Any

from services.engine.rules.models import Condition, ConditionGroup


def evaluate_condition(condition: Condition, context: dict[str, Any]) -> bool:
    key = condition.feature or condition.field
    if key is None:
        return False

    left = context.get(key)
    right = context.get(condition.ref) if condition.ref else condition.value

    if left is None:
        return False
    if right is None:
        if condition.op == "!=":
            return True
        return False

    if condition.op == ">":
        return left > right
    if condition.op == ">=":
        return left >= right
    if condition.op == "<":
        return left < right
    if condition.op == "<=":
        return left <= right
    if condition.op == "==":
        return left == right
    if condition.op == "!=":
        return left != right
    if condition.op == "in":
        if not isinstance(right, (list, tuple, set, frozenset)):
            return False
        return left in right
    if condition.op == "not_in":
        if not isinstance(right, (list, tuple, set, frozenset)):
            return False
        return left not in right
    return False


def evaluate_group(group: ConditionGroup, context: dict[str, Any]) -> bool:
    all_pass = all(
        evaluate_group(item, context) if isinstance(item, ConditionGroup) else evaluate_condition(item, context)
        for item in group.all
    )
    any_pass = True
    if group.any:
        any_pass = any(
            evaluate_group(item, context)
            if isinstance(item, ConditionGroup)
            else evaluate_condition(item, context)
            for item in group.any
        )
    return all_pass and any_pass
