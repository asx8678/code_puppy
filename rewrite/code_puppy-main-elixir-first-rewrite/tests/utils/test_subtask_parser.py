from code_puppy.utils.subtask_parser import (
    parse_subtasks,
    parse_remove_subtasks,
    has_plan,
)


SIMPLE_PLAN = """
Here's what I'll do:

### Tasks

1. Implement foo
   - Add foo.py
   - Wire it up
   Uses: foo.py, main.py

2. Add tests
   Write pytest fixtures for foo.
   Uses: tests/test_foo.py

3. Update docs
"""


def test_parses_simple_plan():
    tasks = parse_subtasks(SIMPLE_PLAN)
    assert len(tasks) == 3
    assert tasks[0].title == "Implement foo"
    assert tasks[1].title == "Add tests"
    assert tasks[2].title == "Update docs"


def test_parses_uses_files():
    tasks = parse_subtasks(SIMPLE_PLAN)
    assert tasks[0].uses_files == ["foo.py", "main.py"]
    assert tasks[1].uses_files == ["tests/test_foo.py"]
    assert tasks[2].uses_files == []


def test_parses_description():
    tasks = parse_subtasks(SIMPLE_PLAN)
    assert "Add foo.py" in tasks[0].description
    assert "Wire it up" in tasks[0].description


def test_no_tasks_section_returns_empty():
    assert parse_subtasks("Just some text, no plan here.") == []


def test_empty_input_returns_empty():
    assert parse_subtasks("") == []


def test_task_section_fallback():
    content = "### Task\n\n1. Do the thing"
    tasks = parse_subtasks(content)
    assert len(tasks) == 1
    assert tasks[0].title == "Do the thing"


def test_strips_backticks_in_uses():
    content = "### Tasks\n\n1. Edit\n   Uses: `foo.py`, `bar.py`"
    tasks = parse_subtasks(content)
    assert tasks[0].uses_files == ["foo.py", "bar.py"]


def test_remove_tasks():
    content = """
### Remove Tasks

- Old task 1
- Old task 2

Some other text
"""
    assert parse_remove_subtasks(content) == ["Old task 1", "Old task 2"]


def test_remove_tasks_empty():
    assert parse_remove_subtasks("no remove section") == []


def test_has_plan_true():
    assert has_plan(SIMPLE_PLAN) is True


def test_has_plan_false_too_few():
    single_task = "### Tasks\n\n1. Only one"
    assert has_plan(single_task, min_tasks=2) is False


def test_has_plan_respects_min_tasks():
    single_task = "### Tasks\n\n1. Only one"
    assert has_plan(single_task, min_tasks=1) is True
