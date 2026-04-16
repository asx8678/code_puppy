"""Tests for the SearchableList widget UX fixes.

Verifies that arrow-key navigation, visible highlight, Enter selection,
and auto-highlight-first-item all work correctly.
"""

import pytest
from code_puppy.tui.widgets.searchable_list import SearchableList, SearchableListItem


# ---------------------------------------------------------------------------
# Unit tests — no Textual app needed
# ---------------------------------------------------------------------------


def test_searchable_list_item_stores_metadata():
    """SearchableListItem stores label, id, badge, disabled."""
    item = SearchableListItem(
        label="GPT-4o", item_id="gpt-4o", badge="active", disabled=False
    )
    assert item.label_text == "GPT-4o"
    assert item.item_id == "gpt-4o"
    assert item.badge_text == "active"
    assert item.item_disabled is False


def test_searchable_list_item_defaults_id_to_label():
    """When item_id is empty, it defaults to the label text."""
    item = SearchableListItem(label="claude-3")
    assert item.item_id == "claude-3"


def test_searchable_list_item_disabled_flag():
    """Disabled flag is stored correctly."""
    item = SearchableListItem(label="old-model", disabled=True)
    assert item.item_disabled is True


def test_searchable_list_can_be_instantiated():
    """SearchableList can be created with default args."""
    widget = SearchableList(id="test-list")
    assert widget is not None


def test_searchable_list_accepts_positional_items():
    """Constructor accepts *items positional args."""
    item1 = SearchableListItem("alpha")
    item2 = SearchableListItem("beta")
    widget = SearchableList(item1, item2, id="test-list")
    assert len(widget._all_items) == 2


def test_searchable_list_placeholder_stored():
    """Custom placeholder is stored for later use."""
    widget = SearchableList(placeholder="🔍 Type to filter")
    assert widget._placeholder == "🔍 Type to filter"


def test_searchable_list_show_search_default():
    """show_search defaults to True."""
    widget = SearchableList()
    assert widget.show_search is True


def test_searchable_list_show_search_false():
    """show_search can be disabled."""
    widget = SearchableList(show_search=False)
    assert widget.show_search is False


def test_searchable_list_item_highlighted_message():
    """ItemHighlighted message stores the item."""
    item = SearchableListItem("test-item")
    msg = SearchableList.ItemHighlighted(item)
    assert msg.item is item


def test_searchable_list_item_selected_message():
    """ItemSelected message stores the item."""
    item = SearchableListItem("test-item")
    msg = SearchableList.ItemSelected(item)
    assert msg.item is item


# ---------------------------------------------------------------------------
# CSS presence checks
# ---------------------------------------------------------------------------


def test_default_css_contains_highlight_rule():
    """DEFAULT_CSS includes the .-highlight rule for blurred visibility."""
    css = SearchableList.DEFAULT_CSS
    assert ".-highlight" in css, "CSS must style highlighted items when not focused"


def test_default_css_uses_accent_background():
    """DEFAULT_CSS uses $accent for highlighted item background."""
    css = SearchableList.DEFAULT_CSS
    assert "$accent" in css


def test_searchable_list_item_default_css_has_padding():
    """SearchableListItem DEFAULT_CSS includes padding."""
    css = SearchableListItem.DEFAULT_CSS
    assert "padding" in css


# ---------------------------------------------------------------------------
# Async integration tests using Textual's test pilot
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_searchable_list_renders_items():
    """Widget renders all items after add_items()."""
    from textual.app import App, ComposeResult
    from textual.widgets import ListView

    class TestApp(App):
        def compose(self) -> ComposeResult:
            yield SearchableList(id="slist")

        async def on_mount(self) -> None:
            items = [
                SearchableListItem("alpha", item_id="alpha"),
                SearchableListItem("beta", item_id="beta"),
                SearchableListItem("gamma", item_id="gamma"),
            ]
            self.query_one("#slist", SearchableList).add_items(items)

    async with TestApp().run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        lv = pilot.app.query_one("#search-list", ListView)
        assert len(lv.children) == 3


@pytest.mark.asyncio
async def test_auto_highlight_first_item_after_add():
    """First item is highlighted (index=0) after add_items()."""
    from textual.app import App, ComposeResult
    from textual.widgets import ListView

    class TestApp(App):
        def compose(self) -> ComposeResult:
            yield SearchableList(id="slist")

        async def on_mount(self) -> None:
            items = [
                SearchableListItem("first", item_id="first"),
                SearchableListItem("second", item_id="second"),
            ]
            self.query_one("#slist", SearchableList).add_items(items)

    async with TestApp().run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        lv = pilot.app.query_one("#search-list", ListView)
        assert lv.index == 0


@pytest.mark.asyncio
async def test_filter_narrows_list():
    """Typing in the search box filters the list."""
    from textual.app import App, ComposeResult
    from textual.widgets import Input, ListView

    class TestApp(App):
        def compose(self) -> ComposeResult:
            yield SearchableList(id="slist")

        async def on_mount(self) -> None:
            items = [
                SearchableListItem("apple"),
                SearchableListItem("apricot"),
                SearchableListItem("banana"),
            ]
            self.query_one("#slist", SearchableList).add_items(items)

    async with TestApp().run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        # Focus the search input and type "ap"
        search_input = pilot.app.query_one("#search-input", Input)
        search_input.focus()
        await pilot.press("a", "p")
        await pilot.pause()
        lv = pilot.app.query_one("#search-list", ListView)
        # Only "apple" and "apricot" should remain
        assert len(lv.children) == 2


@pytest.mark.asyncio
async def test_down_arrow_moves_highlight():
    """Pressing Down moves the list highlight to the next item."""
    from textual.app import App, ComposeResult
    from textual.widgets import Input, ListView

    class TestApp(App):
        def compose(self) -> ComposeResult:
            yield SearchableList(id="slist")

        async def on_mount(self) -> None:
            items = [
                SearchableListItem("first"),
                SearchableListItem("second"),
                SearchableListItem("third"),
            ]
            self.query_one("#slist", SearchableList).add_items(items)

    async with TestApp().run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        search_input = pilot.app.query_one("#search-input", Input)
        search_input.focus()
        await pilot.pause()
        lv = pilot.app.query_one("#search-list", ListView)
        assert lv.index == 0  # first item highlighted after mount
        await pilot.press("down")
        await pilot.pause()
        assert lv.index == 1


@pytest.mark.asyncio
async def test_up_arrow_moves_highlight():
    """Pressing Up moves the list highlight to the previous item."""
    from textual.app import App, ComposeResult
    from textual.widgets import Input, ListView

    class TestApp(App):
        def compose(self) -> ComposeResult:
            yield SearchableList(id="slist")

        async def on_mount(self) -> None:
            items = [
                SearchableListItem("first"),
                SearchableListItem("second"),
                SearchableListItem("third"),
            ]
            self.query_one("#slist", SearchableList).add_items(items)

    async with TestApp().run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        search_input = pilot.app.query_one("#search-input", Input)
        search_input.focus()
        lv = pilot.app.query_one("#search-list", ListView)
        # Move to index 2 first
        lv.index = 2
        await pilot.pause()
        await pilot.press("up")
        await pilot.pause()
        assert lv.index == 1


@pytest.mark.asyncio
async def test_enter_in_search_selects_highlighted_item():
    """Pressing Enter while search has focus fires ItemSelected."""
    from textual.app import App, ComposeResult
    from textual.widgets import Input

    selected_items: list[str] = []

    class TestApp(App):
        def compose(self) -> ComposeResult:
            yield SearchableList(id="slist")

        async def on_mount(self) -> None:
            items = [
                SearchableListItem("alpha", item_id="alpha"),
                SearchableListItem("beta", item_id="beta"),
            ]
            self.query_one("#slist", SearchableList).add_items(items)

        def on_searchable_list_item_selected(
            self, event: SearchableList.ItemSelected
        ) -> None:
            selected_items.append(event.item.item_id)

    async with TestApp().run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        search_input = pilot.app.query_one("#search-input", Input)
        search_input.focus()
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()
        assert "alpha" in selected_items


@pytest.mark.asyncio
async def test_highlighted_item_property():
    """highlighted_item property returns the currently highlighted item."""
    from textual.app import App, ComposeResult

    class TestApp(App):
        def compose(self) -> ComposeResult:
            yield SearchableList(id="slist")

        async def on_mount(self) -> None:
            items = [
                SearchableListItem("first", item_id="first"),
                SearchableListItem("second", item_id="second"),
            ]
            self.query_one("#slist", SearchableList).add_items(items)

    async with TestApp().run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        slist = pilot.app.query_one("#slist", SearchableList)
        item = slist.highlighted_item
        assert item is not None
        assert item.item_id == "first"


@pytest.mark.asyncio
async def test_clear_items_empties_list():
    """clear_items() removes all items from the ListView."""
    from textual.app import App, ComposeResult
    from textual.widgets import ListView

    class TestApp(App):
        def compose(self) -> ComposeResult:
            yield SearchableList(id="slist")

        async def on_mount(self) -> None:
            items = [SearchableListItem("x"), SearchableListItem("y")]
            slist = self.query_one("#slist", SearchableList)
            slist.add_items(items)

    async with TestApp().run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        slist = pilot.app.query_one("#slist", SearchableList)
        slist.clear_items()
        await pilot.pause()
        lv = pilot.app.query_one("#search-list", ListView)
        assert len(lv.children) == 0


@pytest.mark.asyncio
async def test_home_key_goes_to_first_item():
    """Pressing Home jumps to the first item."""
    from textual.app import App, ComposeResult
    from textual.widgets import Input, ListView

    class TestApp(App):
        def compose(self) -> ComposeResult:
            yield SearchableList(id="slist")

        async def on_mount(self) -> None:
            items = [SearchableListItem(f"item-{i}") for i in range(5)]
            self.query_one("#slist", SearchableList).add_items(items)

    async with TestApp().run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        lv = pilot.app.query_one("#search-list", ListView)
        lv.index = 4
        await pilot.pause()
        search_input = pilot.app.query_one("#search-input", Input)
        search_input.focus()
        await pilot.press("home")
        await pilot.pause()
        assert lv.index == 0


@pytest.mark.asyncio
async def test_end_key_goes_to_last_item():
    """Pressing End jumps to the last item."""
    from textual.app import App, ComposeResult
    from textual.widgets import Input, ListView

    class TestApp(App):
        def compose(self) -> ComposeResult:
            yield SearchableList(id="slist")

        async def on_mount(self) -> None:
            items = [SearchableListItem(f"item-{i}") for i in range(5)]
            self.query_one("#slist", SearchableList).add_items(items)

    async with TestApp().run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        search_input = pilot.app.query_one("#search-input", Input)
        search_input.focus()
        await pilot.press("end")
        await pilot.pause()
        lv = pilot.app.query_one("#search-list", ListView)
        assert lv.index == 4


@pytest.mark.asyncio
async def test_filter_then_navigate():
    """After filtering, arrow keys work on the filtered list."""
    from textual.app import App, ComposeResult
    from textual.widgets import Input, ListView

    class TestApp(App):
        def compose(self) -> ComposeResult:
            yield SearchableList(id="slist")

        async def on_mount(self) -> None:
            items = [
                SearchableListItem("apple"),
                SearchableListItem("apricot"),
                SearchableListItem("banana"),
                SearchableListItem("avocado"),
            ]
            self.query_one("#slist", SearchableList).add_items(items)

    async with TestApp().run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        search_input = pilot.app.query_one("#search-input", Input)
        search_input.focus()
        # Filter by "ap" — matches only "apple" and "apricot" (not banana/avocado)
        await pilot.press("a", "p")
        await pilot.pause()
        lv = pilot.app.query_one("#search-list", ListView)
        # Only "apple" and "apricot" should remain
        assert len(lv.children) == 2
        assert lv.index == 0
        await pilot.press("down")
        await pilot.pause()
        assert lv.index == 1
