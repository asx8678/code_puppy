"""Tests for the prompt_store plugin.

Covers:
- Store logic: CRUD, locking, duplication, activation
- Thread safety: concurrent operations
- Atomic writes: crash recovery
- Malformed JSON: backup and reset
- Hook integration: load_custom_prompt
- Command dispatch: /prompts subcommands
- Editor command: shlex.split handling
- Comment stripping: sentinel-style Markdown header preservation
"""

import json
import os
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from code_puppy.plugins.prompt_store.store import PromptStore, PromptTemplate


@pytest.fixture
def temp_store():
    """Create a temporary store for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        store_path = Path(tmpdir) / "prompt_store.json"
        store = PromptStore(store_path)
        yield store


@pytest.fixture
def sample_template(temp_store):
    """Create a sample user template."""
    return temp_store.create_template(
        name="Test Template",
        agent_name="code-puppy",
        content="You are a helpful assistant.",
    )


# =============================================================================
# Store Logic Tests
# =============================================================================


class TestCreateTemplate:
    """Tests for create_template method."""

    def test_create_generates_unique_id(self, temp_store):
        """create_template generates unique ID with pattern agent.custom-N."""
        t1 = temp_store.create_template("First", "code-puppy", "Content 1")
        t2 = temp_store.create_template("Second", "code-puppy", "Content 2")

        assert t1.id.startswith("code-puppy.custom-")
        assert t2.id.startswith("code-puppy.custom-")
        assert t1.id != t2.id

    def test_create_sets_source_user_and_unlocked(self, temp_store):
        """Created templates have source='user' and locked=False."""
        tmpl = temp_store.create_template("Test", "code-puppy", "Content")

        assert tmpl.source == "user"
        assert tmpl.locked is False

    def test_create_sets_timestamps(self, temp_store):
        """create_template sets created_at and updated_at."""
        tmpl = temp_store.create_template("Test", "code-puppy", "Content")

        assert tmpl.created_at is not None
        assert tmpl.updated_at is not None
        assert tmpl.created_at == tmpl.updated_at  # Same on creation

    def test_create_requires_non_empty_agent_name(self, temp_store):
        """create_template raises ValueError if agent_name is empty."""
        with pytest.raises(ValueError, match="agent_name is required"):
            temp_store.create_template("Test", "", "Content")

    def test_create_requires_non_empty_content(self, temp_store):
        """create_template raises ValueError if content is empty."""
        with pytest.raises(ValueError, match="content is required"):
            temp_store.create_template("Test", "code-puppy", "")

    def test_create_different_agents_get_different_ids(self, temp_store):
        """Templates for different agents get different ID prefixes."""
        t1 = temp_store.create_template("T1", "agent-a", "Content")
        t2 = temp_store.create_template("T2", "agent-b", "Content")

        assert t1.id.startswith("agent-a.custom-")
        assert t2.id.startswith("agent-b.custom-")


class TestUpdateTemplate:
    """Tests for update_template method."""

    def test_update_user_template_succeeds(self, temp_store, sample_template):
        """update_template on user template updates content and timestamp."""
        old_updated = sample_template.updated_at

        import time

        time.sleep(0.01)  # Ensure timestamp changes

        updated = temp_store.update_template(sample_template.id, content="New content")

        assert updated.content == "New content"
        assert updated.updated_at != old_updated

    def test_update_template_name(self, temp_store, sample_template):
        """update_template can update the name."""
        updated = temp_store.update_template(sample_template.id, name="New Name")

        assert updated.name == "New Name"

    def test_update_locked_raises_valueerror(self, temp_store):
        """update_template on locked template raises ValueError."""
        # Create a locked template manually
        with temp_store._lock:
            locked = PromptTemplate(
                id="locked.template",
                name="Locked",
                agent_name="test",
                content="Locked content",
                source="default",
                locked=True,
                created_at="2024-01-01",
                updated_at="2024-01-01",
            )
            temp_store._templates[locked.id] = locked
            temp_store._save()

        with pytest.raises(ValueError, match="Template is locked"):
            temp_store.update_template(locked.id, content="New content")

    def test_update_nonexistent_raises_valueerror(self, temp_store):
        """update_template raises ValueError if template not found."""
        with pytest.raises(ValueError, match="Template not found"):
            temp_store.update_template("nonexistent", content="test")


class TestDeleteTemplate:
    """Tests for delete_template method."""

    def test_delete_user_template_succeeds(self, temp_store, sample_template):
        """delete_template on user template returns True."""
        result = temp_store.delete_template(sample_template.id)

        assert result is True
        assert temp_store.get_template(sample_template.id) is None

    def test_delete_nonexistent_returns_false(self, temp_store):
        """delete_template returns False for non-existent template."""
        result = temp_store.delete_template("nonexistent")

        assert result is False

    def test_delete_locked_raises_valueerror(self, temp_store):
        """delete_template on locked template raises ValueError."""
        # Create a locked template manually
        with temp_store._lock:
            locked = PromptTemplate(
                id="locked.template",
                name="Locked",
                agent_name="test",
                content="Locked content",
                source="default",
                locked=True,
                created_at="2024-01-01",
                updated_at="2024-01-01",
            )
            temp_store._templates[locked.id] = locked
            temp_store._save()

        with pytest.raises(ValueError, match="Template is locked"):
            temp_store.delete_template(locked.id)

    def test_delete_clears_active_pointer(self, temp_store, sample_template):
        """Deleting an active template clears it from active pointers."""
        temp_store.set_active_for_agent("code-puppy", sample_template.id)

        temp_store.delete_template(sample_template.id)

        assert temp_store.get_active_for_agent("code-puppy") is None


class TestDuplicateTemplate:
    """Tests for duplicate_template method."""

    def test_duplicate_creates_editable_copy(self, temp_store, sample_template):
        """duplicate_template creates unlocked copy with source=user."""
        duplicate = temp_store.duplicate_template(sample_template.id, "Duplicated")

        assert duplicate.locked is False
        assert duplicate.source == "user"
        assert duplicate.name == "Duplicated"
        assert duplicate.content == sample_template.content
        assert duplicate.id != sample_template.id

    def test_duplicate_works_on_locked_source(self, temp_store):
        """duplicate_template works even on locked defaults."""
        # Create a locked template
        with temp_store._lock:
            locked = PromptTemplate(
                id="locked.default",
                name="Locked Default",
                agent_name="test",
                content="Default content",
                source="default",
                locked=True,
                created_at="2024-01-01",
                updated_at="2024-01-01",
            )
            temp_store._templates[locked.id] = locked
            temp_store._save()

        duplicate = temp_store.duplicate_template(locked.id, "My Version")

        # Duplicate should be editable
        assert duplicate.locked is False
        assert duplicate.source == "user"
        assert duplicate.content == "Default content"

    def test_duplicate_nonexistent_raises_valueerror(self, temp_store):
        """duplicate_template raises ValueError if source not found."""
        with pytest.raises(ValueError, match="Source template not found"):
            temp_store.duplicate_template("nonexistent", "New Name")


class TestActiveTemplate:
    """Tests for set/get/clear_active_for_agent methods."""

    def test_set_and_get_active_roundtrip(self, temp_store, sample_template):
        """set_active_for_agent + get_active_for_agent roundtrip."""
        temp_store.set_active_for_agent("code-puppy", sample_template.id)

        active = temp_store.get_active_for_agent("code-puppy")

        assert active is not None
        assert active.id == sample_template.id

    def test_clear_active_removes_pointer(self, temp_store, sample_template):
        """clear_active_for_agent removes the active pointer."""
        temp_store.set_active_for_agent("code-puppy", sample_template.id)

        temp_store.clear_active_for_agent("code-puppy")

        assert temp_store.get_active_for_agent("code-puppy") is None

    def test_set_active_invalid_template_raises(self, temp_store):
        """set_active_for_agent raises ValueError for non-existent template."""
        with pytest.raises(ValueError, match="Template not found"):
            temp_store.set_active_for_agent("code-puppy", "nonexistent")

    def test_clear_nonexistent_agent_silently_succeeds(self, temp_store):
        """clear_active_for_agent silently succeeds for agent with no active."""
        # Should not raise
        temp_store.clear_active_for_agent("nonexistent-agent")


class TestListTemplates:
    """Tests for list_templates method."""

    def test_list_all_returns_all_templates(self, temp_store):
        """list_templates returns all templates when no filter."""
        t1 = temp_store.create_template("T1", "agent-a", "Content")
        t2 = temp_store.create_template("T2", "agent-b", "Content")

        all_templates = temp_store.list_templates()

        assert len(all_templates) == 2
        ids = [t.id for t in all_templates]
        assert t1.id in ids
        assert t2.id in ids

    def test_list_with_agent_filter(self, temp_store):
        """list_templates(agent_name=X) filters correctly."""
        t1 = temp_store.create_template("T1", "agent-a", "Content")
        t2 = temp_store.create_template("T2", "agent-b", "Content")
        t3 = temp_store.create_template("T3", "agent-a", "Content")

        filtered = temp_store.list_templates(agent_name="agent-a")

        assert len(filtered) == 2
        ids = [t.id for t in filtered]
        assert t1.id in ids
        assert t3.id in ids
        assert t2.id not in ids

    def test_list_returns_sorted_results(self, temp_store):
        """list_templates returns templates sorted by (agent_name, name)."""
        temp_store.create_template("Zebra", "agent-b", "Content")
        temp_store.create_template("Apple", "agent-a", "Content")
        temp_store.create_template("Banana", "agent-a", "Content")

        results = temp_store.list_templates()

        # Should be sorted by (agent_name, name)
        assert results[0].agent_name == "agent-a"
        assert results[0].name == "Apple"
        assert results[1].agent_name == "agent-a"
        assert results[1].name == "Banana"
        assert results[2].agent_name == "agent-b"
        assert results[2].name == "Zebra"


class TestThreadSafety:
    """Tests for thread safety."""

    def test_concurrent_create_doesnt_corrupt(self, temp_store):
        """Concurrent create operations don't corrupt the store."""
        errors = []

        def create_template(i):
            try:
                temp_store.create_template(
                    f"Template {i}", "test-agent", f"Content {i}"
                )
            except Exception as e:
                errors.append(e)

        # Create many templates concurrently
        with ThreadPoolExecutor(max_workers=10) as executor:
            list(executor.map(create_template, range(50)))

        assert len(errors) == 0, f"Errors occurred: {errors}"

        # All templates should exist with unique IDs
        templates = temp_store.list_templates()
        assert len(templates) == 50
        ids = [t.id for t in templates]
        assert len(set(ids)) == 50  # All unique

    def test_concurrent_update_and_read(self, temp_store, sample_template):
        """Concurrent updates and reads don't crash."""
        errors = []
        results = []

        def update_template(i):
            try:
                result = temp_store.update_template(
                    sample_template.id, content=f"Updated {i}"
                )
                results.append(result)
            except Exception as e:
                errors.append(e)

        def read_template(i):
            try:
                t = temp_store.get_template(sample_template.id)
                results.append(t)
            except Exception as e:
                errors.append(e)

        # Mix of reads and updates
        with ThreadPoolExecutor(max_workers=10) as executor:
            for i in range(20):
                if i % 2 == 0:
                    executor.submit(update_template, i)
                else:
                    executor.submit(read_template, i)

        assert len(errors) == 0, f"Errors occurred: {errors}"


class TestAtomicWrites:
    """Tests for atomic write behavior."""

    def test_atomic_write_no_corruption_on_crash(self, temp_store):
        """Simulated crash mid-write doesn't corrupt store."""
        # Create initial template
        temp_store.create_template("Initial", "test", "Initial content")

        # Verify store is valid
        store_path = temp_store.get_store_path()
        with open(store_path, encoding="utf-8") as f:
            data = json.load(f)
        assert len(data["templates"]) == 1

        # Manually simulate what a crash would leave (a temp file)
        temp_path = store_path.with_suffix(".tmp")
        temp_path.write_text("corrupted garbage", encoding="utf-8")

        # New store should ignore the temp file and load the valid store
        new_store = PromptStore(store_path)
        templates = new_store.list_templates()
        assert len(templates) == 1

        # Clean up
        if temp_path.exists():
            temp_path.unlink()


class TestMalformedJSON:
    """Tests for malformed JSON handling."""

    def test_backup_and_reset_on_malformed_json(self, temp_store):
        """Malformed JSON causes backup and fresh start."""
        store_path = temp_store.get_store_path()

        # Create a template first
        temp_store.create_template("Test", "agent", "Content")

        # Corrupt the JSON
        store_path.write_text("this is not valid json {", encoding="utf-8")

        # Loading should back up and reset
        new_store = PromptStore(store_path)

        # Store should be empty (fresh start)
        assert len(new_store.list_templates()) == 0

        # Backup file should exist
        backup_path = store_path.with_suffix(".json.bak")
        assert backup_path.exists()


# =============================================================================
# Hook Integration Tests
# =============================================================================


class TestLoadCustomPrompt:
    """Tests for load_custom_prompt hook function."""

    @patch("code_puppy.plugins.prompt_store.commands.get_current_agent_name")
    @patch("code_puppy.plugins.prompt_store.commands._get_store")
    def test_returns_none_when_no_active_template(self, mock_get_store, mock_get_agent):
        """load_custom_prompt returns None when no active template."""
        from code_puppy.plugins.prompt_store.commands import load_custom_prompt

        mock_get_agent.return_value = "code-puppy"

        # Mock store with no active template
        mock_store = MagicMock()
        mock_store.get_active_for_agent.return_value = None
        mock_get_store.return_value = mock_store

        result = load_custom_prompt()

        assert result is None

    @patch("code_puppy.plugins.prompt_store.commands.get_current_agent_name")
    @patch("code_puppy.plugins.prompt_store.commands._get_store")
    def test_returns_string_with_custom_content(self, mock_get_store, mock_get_agent):
        """load_custom_prompt returns string with custom content when active."""
        from code_puppy.plugins.prompt_store.commands import load_custom_prompt

        mock_get_agent.return_value = "code-puppy"

        # Mock active template
        mock_template = MagicMock()
        mock_template.content = "Custom system prompt"
        mock_store = MagicMock()
        mock_store.get_active_for_agent.return_value = mock_template
        mock_get_store.return_value = mock_store

        result = load_custom_prompt()

        assert result is not None
        assert result == "Custom system prompt"

    @patch("code_puppy.plugins.prompt_store.commands.get_current_agent_name")
    def test_returns_none_on_exception(self, mock_get_agent):
        """load_custom_prompt returns None if getting agent fails."""
        from code_puppy.plugins.prompt_store.commands import load_custom_prompt

        mock_get_agent.side_effect = Exception("Some error")

        result = load_custom_prompt()

        assert result is None


# =============================================================================
# Prompt Hook Contract Tests
# =============================================================================


class TestPromptHookContract:
    """Tests for the prompt_store load_prompt hook contract."""

    @patch("code_puppy.plugins.prompt_store.commands.get_current_agent_name")
    @patch("code_puppy.plugins.prompt_store.commands._get_store")
    def test_prompt_store_contributes_via_load_prompt(self, mock_get_store, mock_get_agent):
        """prompt_store returns a string via load_prompt, not a dict."""
        from code_puppy.plugins.prompt_store.commands import load_custom_prompt

        mock_get_agent.return_value = "code-puppy"

        mock_template = MagicMock()
        mock_template.content = "Custom prompt instructions"
        mock_store = MagicMock()
        mock_store.get_active_for_agent.return_value = mock_template
        mock_get_store.return_value = mock_store

        result = load_custom_prompt()

        assert isinstance(result, str)
        assert result == "Custom prompt instructions"

    def test_load_prompt_hook_signature_matches(self):
        """load_custom_prompt has the load_prompt signature: () -> str | None."""
        import inspect

        from code_puppy.plugins.prompt_store.commands import load_custom_prompt

        sig = inspect.signature(load_custom_prompt)
        params = list(sig.parameters.keys())

        assert params == [], f"load_custom_prompt should take no args, got {params}"
        assert sig.return_annotation == (str | None)


# =============================================================================
# Command Dispatch Tests
# =============================================================================


class TestHandlePromptsCommand:
    """Tests for handle_prompts_command dispatcher."""

    @patch("code_puppy.plugins.prompt_store.commands._handle_list")
    def test_list_command_dispatched(self, mock_list):
        """list subcommand is dispatched correctly."""
        from code_puppy.plugins.prompt_store.commands import handle_prompts_command

        result = handle_prompts_command("/prompts list code-puppy", "prompts")

        assert result is True  # Handled
        mock_list.assert_called_once_with(["code-puppy"])

    @patch("code_puppy.plugins.prompt_store.commands._handle_list")
    def test_default_to_list_when_no_subcommand(self, mock_list):
        """Bare /prompts defaults to list."""
        from code_puppy.plugins.prompt_store.commands import handle_prompts_command

        result = handle_prompts_command("/prompts", "prompts")

        assert result is True
        mock_list.assert_called_once_with([])

    @patch("code_puppy.plugins.prompt_store.commands._handle_show")
    def test_show_command_dispatched(self, mock_show):
        """show subcommand is dispatched correctly."""
        from code_puppy.plugins.prompt_store.commands import handle_prompts_command

        result = handle_prompts_command("/prompts show my-template", "prompts")

        assert result is True
        mock_show.assert_called_once_with(["my-template"])

    @patch("code_puppy.plugins.prompt_store.commands._handle_help")
    def test_help_command_dispatched(self, mock_help):
        """help subcommand is dispatched correctly."""
        from code_puppy.plugins.prompt_store.commands import handle_prompts_command

        result = handle_prompts_command("/prompts help", "prompts")

        assert result is True
        mock_help.assert_called_once()

    def test_unknown_command_returns_none(self):
        """Unknown command name returns None (not handled)."""
        from code_puppy.plugins.prompt_store.commands import handle_prompts_command

        result = handle_prompts_command("/other list", "other")

        assert result is None  # Not handled

    @patch("code_puppy.plugins.prompt_store.commands.emit_error")
    def test_unknown_subcommand_shows_error(self, mock_error):
        """Unknown subcommand shows error but returns True (handled)."""
        from code_puppy.plugins.prompt_store.commands import handle_prompts_command

        result = handle_prompts_command("/prompts unknown", "prompts")

        assert result is True  # We handled it (by showing error)
        mock_error.assert_called_once()


# =============================================================================
# Editor Command Tests (shlex.split)
# =============================================================================


class TestEditorCommand:
    """Tests for editor command tokenization with shlex.split."""

    @patch.dict(os.environ, {"EDITOR": "vim"}, clear=True)
    def test_simple_editor_command(self):
        """Simple editor without args works."""
        from code_puppy.plugins.prompt_store.commands import _get_editor_command

        result = _get_editor_command()
        assert result == ["vim"]

    @patch.dict(os.environ, {"EDITOR": "code --wait"}, clear=True)
    def test_editor_with_args_code_wait(self):
        """Editor with args like 'code --wait' is properly tokenized."""
        from code_puppy.plugins.prompt_store.commands import _get_editor_command

        result = _get_editor_command()
        assert result == ["code", "--wait"]

    @patch.dict(os.environ, {"EDITOR": "subl -n -w"}, clear=True)
    def test_editor_with_multiple_args(self):
        """Editor with multiple args is properly tokenized."""
        from code_puppy.plugins.prompt_store.commands import _get_editor_command

        result = _get_editor_command()
        assert result == ["subl", "-n", "-w"]

    @patch.dict(os.environ, {"VISUAL": "emacs -nw", "EDITOR": "vim"}, clear=True)
    def test_visual_takes_priority(self):
        """VISUAL takes priority over EDITOR."""
        from code_puppy.plugins.prompt_store.commands import _get_editor_command

        result = _get_editor_command()
        assert result == ["emacs", "-nw"]

    @patch.dict(os.environ, {}, clear=True)
    def test_default_editor_nano_on_unix(self):
        """Default editor is nano on Unix when no env vars set."""
        from code_puppy.plugins.prompt_store.commands import _get_editor_command

        with patch("os.name", "posix"):
            result = _get_editor_command()
            assert result == ["nano"]


# =============================================================================
# Comment Stripping Tests (sentinel-style)
# =============================================================================


class TestStripEditorComments:
    """Tests for sentinel-style comment stripping using '# // ' prefix."""

    def test_strips_lines_starting_with_sentinel(self):
        """Lines starting with '# // ' are stripped as editor comments."""
        from code_puppy.plugins.prompt_store.commands import _strip_editor_comments

        content = "# // This is an editor comment\nActual content\n# // Another editor comment"
        result = _strip_editor_comments(content)
        assert result == "Actual content"

    def test_preserves_markdown_headers(self):
        """Markdown headers like '# Heading' are preserved."""
        from code_puppy.plugins.prompt_store.commands import _strip_editor_comments

        content = "# Heading 1\nSome text\n## Heading 2\n### Heading 3"
        result = _strip_editor_comments(content)
        assert "# Heading 1" in result
        assert "## Heading 2" in result
        assert "### Heading 3" in result
        assert "Some text" in result

    def test_preserves_regular_code_comments(self):
        """Regular code comments '# ' are preserved (not editor comments)."""
        from code_puppy.plugins.prompt_store.commands import _strip_editor_comments

        content = "# TODO: fix this\n# FIXME: handle edge case\nActual code"
        result = _strip_editor_comments(content)
        assert "# TODO: fix this" in result
        assert "# FIXME: handle edge case" in result
        assert "Actual code" in result

    def test_preserves_hash_without_space(self):
        """Lines with just '#' or '#Text' are preserved."""
        from code_puppy.plugins.prompt_store.commands import _strip_editor_comments

        content = "#\n#NoSpace\n# With space is preserved"
        result = _strip_editor_comments(content)
        assert "#" in result
        assert "#NoSpace" in result
        assert "# With space is preserved" in result

    def test_handles_empty_content(self):
        """Empty content returns empty string."""
        from code_puppy.plugins.prompt_store.commands import _strip_editor_comments

        result = _strip_editor_comments("")
        assert result == ""

    def test_handles_only_editor_comments(self):
        """Content with only editor comments returns empty string."""
        from code_puppy.plugins.prompt_store.commands import _strip_editor_comments

        content = "# // Comment 1\n# // Comment 2"
        result = _strip_editor_comments(content)
        assert result == ""

    def test_preserves_indented_content(self):
        """Indented lines are preserved unless they have sentinel."""
        from code_puppy.plugins.prompt_store.commands import _strip_editor_comments

        content = "    code line\n    # // indented editor comment"
        result = _strip_editor_comments(content)
        assert "code line" in result
        assert "indented editor comment" not in result

    def test_handles_mixed_markdown_and_editor_comments(self):
        """Real-world mix: Markdown headers, code comments, editor comments."""
        from code_puppy.plugins.prompt_store.commands import _strip_editor_comments

        content = """# // Editing: My Template (template.id)
# // Lines starting with '# // ' are ignored (all other lines preserved)

# My Custom Header
This is the actual content.
# TODO: add more examples
## Subheader
More content.
# // Another editor comment at end
"""
        result = _strip_editor_comments(content)
        # Markdown headers preserved
        assert "# My Custom Header" in result
        assert "## Subheader" in result
        # Code comments preserved
        assert "# TODO: add more examples" in result
        # Editor comments stripped (have '# // ')
        assert "Editing:" not in result
        assert "Lines starting with" not in result
        assert "Another editor comment" not in result
        # Content preserved
        assert "This is the actual content" in result
        assert "More content" in result


# =============================================================================
# Edge Case Tests
# =============================================================================


class TestEdgeCases:
    """Edge case tests."""

    def test_empty_store_no_errors(self, temp_store):
        """Empty store operations don't crash."""
        # These should all work on an empty store
        assert temp_store.list_templates() == []
        assert temp_store.get_template("nonexistent") is None
        assert temp_store.get_active_for_agent("any-agent") is None

    def test_template_id_collision_handled(self, temp_store):
        """ID collision prevention works when many templates exist."""
        # Create many templates to force ID increment
        for i in range(100):
            temp_store.create_template(f"T{i}", "test-agent", f"Content {i}")

        # Create one more - should get unique ID
        t = temp_store.create_template("Final", "test-agent", "Content")

        # Should be unique
        ids = [tmpl.id for tmpl in temp_store.list_templates()]
        assert len(set(ids)) == 101
        assert t.id == "test-agent.custom-101"

    def test_store_persists_and_reloads(self, temp_store):
        """Store persists to disk and reloads correctly."""
        store_path = temp_store.get_store_path()

        # Create template
        original = temp_store.create_template("Test", "code-puppy", "Content")
        template_id = original.id

        # Create new store pointing to same file
        new_store = PromptStore(store_path)

        # Should load the template
        loaded = new_store.get_template(template_id)
        assert loaded is not None
        assert loaded.name == "Test"
        assert loaded.content == "Content"

    def test_active_persists_and_reloads(self, temp_store, sample_template):
        """Active pointer persists and reloads correctly."""
        store_path = temp_store.get_store_path()

        # Set active
        temp_store.set_active_for_agent("code-puppy", sample_template.id)

        # Create new store
        new_store = PromptStore(store_path)

        # Active should be preserved
        active = new_store.get_active_for_agent("code-puppy")
        assert active is not None
        assert active.id == sample_template.id


# =============================================================================
# Help Menu Tests
# =============================================================================


class TestGetPromptsHelp:
    """Tests for get_prompts_help function."""

    def test_returns_list_of_tuples(self):
        """get_prompts_help returns list of (command, description) tuples."""
        from code_puppy.plugins.prompt_store.commands import get_prompts_help

        help_entries = get_prompts_help()

        assert isinstance(help_entries, list)
        assert len(help_entries) > 0

        for entry in help_entries:
            assert isinstance(entry, tuple)
            assert len(entry) == 2
            assert isinstance(entry[0], str)
            assert isinstance(entry[1], str)
            assert entry[0].startswith("/prompts")


# =============================================================================
# Serialization Tests
# =============================================================================


class TestSerialization:
    """Tests for template serialization."""

    def test_template_to_dict(self):
        """PromptTemplate.to_dict() produces correct dict."""
        tmpl = PromptTemplate(
            id="test.id",
            name="Test",
            agent_name="agent",
            content="Content",
            source="user",
            locked=False,
            created_at="2024-01-01T00:00:00",
            updated_at="2024-01-01T00:00:00",
        )

        d = tmpl.to_dict()

        assert d["id"] == "test.id"
        assert d["name"] == "Test"
        assert d["agent_name"] == "agent"
        assert d["content"] == "Content"
        assert d["source"] == "user"
        assert d["locked"] is False

    def test_template_from_dict(self):
        """PromptTemplate.from_dict() parses correctly."""
        d = {
            "id": "test.id",
            "name": "Test",
            "agent_name": "agent",
            "content": "Content",
            "source": "default",
            "locked": True,
            "created_at": "2024-01-01T00:00:00",
            "updated_at": "2024-01-01T00:00:00",
        }

        tmpl = PromptTemplate.from_dict(d)

        assert tmpl.id == "test.id"
        assert tmpl.name == "Test"
        assert tmpl.source == "default"
        assert tmpl.locked is True

    def test_template_defaults_for_missing_fields(self):
        """from_dict uses sensible defaults for missing fields."""
        d = {
            "id": "test.id",
            "name": "Test",
            "agent_name": "agent",
            "content": "Content",
            "created_at": "2024-01-01",
            "updated_at": "2024-01-01",
            # Missing: source, locked
        }

        tmpl = PromptTemplate.from_dict(d)

        assert tmpl.source == "user"
        assert tmpl.locked is False
