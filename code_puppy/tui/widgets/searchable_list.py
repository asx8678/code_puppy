"""Searchable list widget — filterable ListView with search input.

Replaces the manual PAGE_SIZE pagination used across all menus.
Provides real scrolling + instant search filtering.
"""

from textual.app import ComposeResult
from textual.message import Message
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Input, Label, ListItem, ListView


class SearchableListItem(ListItem):
    """A list item that stores its original data for filtering."""

    def __init__(
        self,
        label: str,
        item_id: str = "",
        badge: str = "",
        disabled: bool = False,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self.label_text = label
        self.item_id = item_id or label
        self.badge_text = badge
        self.item_disabled = disabled

    def compose(self) -> ComposeResult:
        text = self.label_text
        if self.badge_text:
            text += f" [{self.badge_text}]"
        label = Label(text)
        if self.item_disabled:
            label.add_class("--disabled")
        yield label


class SearchableList(Widget):
    """A searchable, scrollable list with filter input.

    Replaces the manual PAGE_SIZE + pagination pattern.

    Usage:
        list_widget = SearchableList(id="models")
        list_widget.add_items([
            SearchableListItem("gpt-5.2", badge="active"),
            SearchableListItem("claude-sonnet-4"),
        ])

    Messages:
        SearchableList.ItemHighlighted: Fired when cursor moves to new item
        SearchableList.ItemSelected: Fired when Enter is pressed on an item
    """

    filter_text = reactive("", layout=False)
    show_search = reactive(True)

    class ItemHighlighted(Message):
        """Sent when a list item is highlighted (cursor moved)."""

        def __init__(self, item: SearchableListItem) -> None:
            super().__init__()
            self.item = item

    class ItemSelected(Message):
        """Sent when a list item is selected (Enter pressed)."""

        def __init__(self, item: SearchableListItem) -> None:
            super().__init__()
            self.item = item

    def __init__(
        self,
        *,
        placeholder: str = "🔍 Search...",
        show_search: bool = True,
        name: str | None = None,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(name=name, id=id, classes=classes)
        self.show_search = show_search
        self._placeholder = placeholder
        self._all_items: list[SearchableListItem] = []

    def compose(self) -> ComposeResult:
        if self.show_search:
            yield Input(placeholder=self._placeholder, id="search-input")
        yield ListView(id="search-list")

    def add_items(self, items: list[SearchableListItem]) -> None:
        """Add items to the list."""
        self._all_items = items
        self._apply_filter()

    def clear_items(self) -> None:
        """Remove all items."""
        self._all_items.clear()
        list_view = self.query_one("#search-list", ListView)
        list_view.clear()

    def _apply_filter(self) -> None:
        """Apply the current filter to the list."""
        list_view = self.query_one("#search-list", ListView)
        list_view.clear()

        filter_lower = self.filter_text.lower()
        for item in self._all_items:
            if not filter_lower or filter_lower in item.label_text.lower():
                list_view.append(item)

    def on_input_changed(self, event: Input.Changed) -> None:
        """Filter list when search input changes."""
        if event.input.id == "search-input":
            self.filter_text = event.value
            self._apply_filter()

    def on_list_view_highlighted(self, event: ListView.Highlighted) -> None:
        """Re-emit as our own message type."""
        if event.item and isinstance(event.item, SearchableListItem):
            self.post_message(self.ItemHighlighted(event.item))

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        """Re-emit as our own message type."""
        if event.item and isinstance(event.item, SearchableListItem):
            self.post_message(self.ItemSelected(event.item))

    @property
    def highlighted_item(self) -> SearchableListItem | None:
        """Get the currently highlighted item."""
        list_view = self.query_one("#search-list", ListView)
        if list_view.highlighted_child and isinstance(
            list_view.highlighted_child, SearchableListItem
        ):
            return list_view.highlighted_child
        return None
