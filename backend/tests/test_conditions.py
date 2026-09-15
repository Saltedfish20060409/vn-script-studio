"""条件表达式：解析 / 求值 / 导出。

这套语法要同时满足三件事：前端试玩器能求值、导出 Ren'Py 时不可注入、作者一眼看懂。
用例表与 frontend/src/lib/conditions.test.ts 保持一致（两侧是镜像实现）。
"""

from __future__ import annotations

import pytest

from app.core.conditions import (
    ConditionError,
    condition_keys,
    condition_source,
    evaluate_condition,
    parse_condition,
    render_condition,
)


def test_parse_simple_comparisons():
    cond = parse_condition("affection >= 3")
    assert len(cond) == 1
    assert cond[0].key == "affection"
    assert cond[0].op == ">="
    assert cond[0].value == 3


def test_bare_identifier_is_truthiness():
    cond = parse_condition("saw_umbrella")
    assert cond[0].key == "saw_umbrella"
    assert cond[0].op is None


def test_and_joins_multiple_terms():
    cond = parse_condition("affection >= 3 and flag == true")
    assert [c.key for c in cond] == ["affection", "flag"]
    assert condition_keys(cond) == ["affection", "flag"]
    assert len(parse_condition("a >= 1 && b <= 2")) == 2
    assert len(parse_condition("a >= 1 并且 b <= 2")) == 2


def test_values_types():
    assert parse_condition('name == "由纪"')[0].value == "由纪"
    assert parse_condition("flag == true")[0].value is True
    assert parse_condition("n == 2.5")[0].value == 2.5
    assert parse_condition("n == -1")[0].value == -1


def test_empty_condition_is_always_true():
    assert parse_condition("") == ()
    assert parse_condition(None) == ()
    assert evaluate_condition((), {}) is True
    assert condition_source("") == "True"


@pytest.mark.parametrize(
    "bad",
    [
        "affection >=",
        ">= 3",
        "affection ~~ 3",
        'affection == "未闭合',
        "1affection >= 3",
    ],
)
def test_invalid_conditions_raise(bad):
    with pytest.raises(ConditionError):
        parse_condition(bad)


def test_evaluate_covers_comparisons_and_and():
    vars_ = {"affection": 3, "flag": True, "name": "由纪", "score": "5"}

    assert evaluate_condition(parse_condition("affection >= 3"), vars_) is True
    assert evaluate_condition(parse_condition("affection > 3"), vars_) is False
    assert evaluate_condition(parse_condition("affection <= 3"), vars_) is True
    assert evaluate_condition(parse_condition("affection < 3"), vars_) is False
    assert evaluate_condition(parse_condition("affection == 3"), vars_) is True
    assert evaluate_condition(parse_condition("affection != 3"), vars_) is False
    assert evaluate_condition(parse_condition("flag"), vars_) is True
    assert evaluate_condition(parse_condition('name == "由纪"'), vars_) is True
    # 数字与字符串混用做温和转换（作者从表单里拿到的常是字符串）
    assert evaluate_condition(parse_condition("score >= 3"), vars_) is True
    assert (
        evaluate_condition(parse_condition("affection >= 3 and flag"), vars_) is True
    )
    assert (
        evaluate_condition(parse_condition("affection >= 9 and flag"), vars_) is False
    )


def test_undefined_variables_are_falsey_not_errors():
    assert evaluate_condition(parse_condition("never_set"), {}) is False
    assert evaluate_condition(parse_condition("never_set >= 1"), {}) is False
    assert evaluate_condition(parse_condition("never_set == 0"), {}) is True


def test_render_is_renpy_safe():
    assert condition_source("affection >= 3") == "affection >= 3"
    assert condition_source("flag == true") == "flag == True"
    assert condition_source('name == "由纪"') == 'name == "由纪"'
    assert condition_source("affection >= 3 and saw") == "affection >= 3 and saw"


def test_render_escapes_quotes_so_it_cannot_escape_into_code():
    cond = parse_condition('name == "a\\"b"')
    rendered = render_condition(cond)
    # 引号被转义，且整串里不出现未转义的收尾引号后接代码
    assert rendered.startswith("name == ")
    assert '\\"' in rendered
    assert "\n" not in rendered
