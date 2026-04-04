"""TypeScript AST extractor using Tree-sitter.

Extends JavaScript extractor with TypeScript-specific constructs:
- Interfaces, type aliases, enums
- Generic type parameters
- Abstract classes and methods
- Property definitions
"""

from typing import TYPE_CHECKING

from .javascript_extractor import JavaScriptExtractor

if TYPE_CHECKING:
    from tree_sitter import Tree

    from ..symbol_graph import SymbolGraph


class TypeScriptExtractor(JavaScriptExtractor):
    """Extracts TypeScript symbols from Tree-sitter AST.

    Extends JavaScriptExtractor with TypeScript-specific constructs.
    """

    def extract(
        self,
        tree: "Tree",
        source: str | bytes,
        file_path: str,
        graph: "SymbolGraph",
    ) -> int:
        """Extract TypeScript symbols including TS-specific constructs."""
        from ..symbol_graph import Location, Reference, Symbol, SymbolKind

        root = tree.root_node
        count = 0

        def process_node(node, parent_name: str = "", class_name: str = ""):
            nonlocal count

            # Interface declaration: interface Name { ... }
            if node.type == "interface_declaration":
                name_node = node.child_by_field_name("name")
                if name_node:
                    name = self._get_node_text(name_node, source)
                    location = self._get_location(node, file_path)

                    # Get type parameters if any
                    type_params = ""
                    for child in node.children:
                        if child.type == "type_parameters":
                            type_params = self._get_node_text(child, source)
                            break

                    signature = f"interface {name}{type_params}"

                    symbol = Symbol(
                        name=name,
                        kind=SymbolKind.INTERFACE,
                        location=location,
                        signature=signature,
                    )
                    graph.add_symbol(symbol)
                    count += 1

                    # Process interface body
                    body_node = node.child_by_field_name("body")
                    if body_node:
                        for child in body_node.children:
                            if child.type in ("property_signature", "method_signature"):
                                self._extract_interface_member(
                                    child, name, source, file_path, graph
                                )

            # Type alias: type Name = ...
            elif node.type == "type_alias_declaration":
                name_node = node.child_by_field_name("name")
                if name_node:
                    name = self._get_node_text(name_node, source)
                    location = self._get_location(node, file_path)

                    # Get type value
                    type_node = node.child_by_field_name("value")
                    type_value = ""
                    if type_node:
                        type_value = self._get_node_text(type_node, source)

                    signature = f"type {name} = {type_value}"

                    symbol = Symbol(
                        name=name,
                        kind=SymbolKind.TYPE_ALIAS,
                        location=location,
                        signature=signature,
                    )
                    graph.add_symbol(symbol)
                    count += 1

            # Enum declaration: enum Name { ... }
            elif node.type == "enum_declaration":
                name_node = node.child_by_field_name("name")
                if name_node:
                    name = self._get_node_text(name_node, source)
                    location = self._get_location(node, file_path)

                    symbol = Symbol(
                        name=name,
                        kind=SymbolKind.ENUM,
                        location=location,
                        signature=f"enum {name}",
                    )
                    graph.add_symbol(symbol)
                    count += 1

                    # Process enum body for members
                    body_node = node.child_by_field_name("body")
                    if body_node:
                        for child in body_node.children:
                            if child.type == "enum_member":
                                member_name_node = child.child_by_field_name("name")
                                if member_name_node:
                                    member_name = self._get_node_text(member_name_node, source)
                                    member_loc = self._get_location(child, file_path)
                                    member_symbol = Symbol(
                                        name=f"{name}.{member_name}",
                                        kind=SymbolKind.CONSTANT,
                                        location=member_loc,
                                        parent=name,
                                    )
                                    graph.add_symbol(member_symbol)

                                    ref = Reference(
                                        source=name,
                                        target=f"{name}.{member_name}",
                                        kind="contains",
                                        location=member_loc,
                                    )
                                    graph.add_reference(ref)

            # Abstract class method
            elif node.type == "abstract_method_signature":
                name_node = node.child_by_field_name("name")
                if name_node and class_name:
                    name = self._get_node_text(name_node, source)
                    location = self._get_location(node, file_path)

                    params_node = node.child_by_field_name("parameters")
                    params_text = ""
                    if params_node:
                        params_text = self._get_node_text(params_node, source)

                    # Check for return type
                    return_type = ""
                    for child in node.children:
                        if child.type == "type_annotation":
                            return_type = self._get_node_text(child, source)
                            break

                    signature = f"abstract {name}{params_text}{return_type}"

                    symbol = Symbol(
                        name=name,
                        kind=SymbolKind.METHOD,
                        location=location,
                        signature=signature,
                        parent=class_name,
                    )
                    graph.add_symbol(symbol)

                    ref = Reference(
                        source=class_name,
                        target=name,
                        kind="contains",
                        location=location,
                    )
                    graph.add_reference(ref)

                    count += 1

            # Property definition in class
            elif node.type == "property_definition":
                name_node = node.child_by_field_name("name")
                if name_node and class_name:
                    name = self._get_node_text(name_node, source)
                    location = self._get_location(node, file_path)

                    # Check for type annotation
                    type_annot = ""
                    for child in node.children:
                        if child.type == "type_annotation":
                            type_annot = self._get_node_text(child, source)
                            break

                    # Check if readonly, static, etc.
                    modifiers = []
                    if any(child.type == "readonly" for child in node.children):
                        modifiers.append("readonly")
                    if any(child.type == "static" for child in node.children):
                        modifiers.append("static")

                    mod_str = " ".join(modifiers) + " " if modifiers else ""
                    signature = f"{mod_str}{name}{type_annot}"

                    kind = SymbolKind.VARIABLE

                    symbol = Symbol(
                        name=name,
                        kind=kind,
                        location=location,
                        signature=signature,
                        parent=class_name,
                    )
                    graph.add_symbol(symbol)

                    ref = Reference(
                        source=class_name,
                        target=name,
                        kind="contains",
                        location=location,
                    )
                    graph.add_reference(ref)

                    count += 1

            # Module declaration: namespace / module
            elif node.type == "module_declaration":
                name_node = node.child_by_field_name("name")
                if name_node:
                    name = self._get_node_text(name_node, source)
                    location = self._get_location(node, file_path)

                    symbol = Symbol(
                        name=name,
                        kind=SymbolKind.MODULE,
                        location=location,
                        signature=f"namespace {name}",
                    )
                    graph.add_symbol(symbol)
                    count += 1

                    # Process body with namespace as parent
                    body_node = node.child_by_field_name("body")
                    if body_node:
                        for child in body_node.children:
                            process_node(child, name, class_name)

            # Process other nodes with JavaScript extractor
            else:
                # Fall back to parent class processing for JS constructs
                pass

            # Recursively process children
            for child in node.children:
                process_node(child, parent_name, class_name)

        # Process all nodes
        for child in root.children:
            process_node(child, "", "")

        # Also run the JavaScript extractor for standard JS constructs
        # but we need to avoid double-counting
        # For now, we handle everything above

        return count

    def _extract_interface_member(
        self,
        node,
        interface_name: str,
        source: str | bytes,
        file_path: str,
        graph: "SymbolGraph",
    ) -> None:
        """Extract a member from an interface."""
        from ..symbol_graph import Location, Reference, Symbol, SymbolKind

        location = self._get_location(node, file_path)

        name_node = node.child_by_field_name("name")
        if not name_node:
            return

        name = self._get_node_text(name_node, source)

        # Get type annotation for properties
        type_annot = ""
        for child in node.children:
            if child.type == "type_annotation":
                type_annot = self._get_node_text(child, source)
                break

        # Get parameters for methods
        params_node = node.child_by_field_name("parameters")
        params_text = ""
        if params_node:
            params_text = self._get_node_text(params_node, source)

        if node.type == "property_signature":
            signature = f"{name}{type_annot}"
            kind = SymbolKind.VARIABLE
        else:  # method_signature
            signature = f"{name}{params_text}{type_annot}"
            kind = SymbolKind.METHOD

        symbol = Symbol(
            name=name,
            kind=kind,
            location=location,
            signature=signature,
            parent=interface_name,
        )
        graph.add_symbol(symbol)

        ref = Reference(
            source=interface_name,
            target=name,
            kind="contains",
            location=location,
        )
        graph.add_reference(ref)
