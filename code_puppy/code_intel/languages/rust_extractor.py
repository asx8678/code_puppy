"""Rust AST extractor using Tree-sitter.

Extracts: functions, methods, structs, enums, traits, impls, modules, imports, and calls.
"""

from typing import TYPE_CHECKING

from .base import BaseExtractor

if TYPE_CHECKING:
    from tree_sitter import Tree

    from ..symbol_graph import SymbolGraph


class RustExtractor(BaseExtractor):
    """Extracts Rust symbols from Tree-sitter AST."""

    def extract(
        self,
        tree: "Tree",
        source: str | bytes,
        file_path: str,
        graph: "SymbolGraph",
    ) -> int:
        """Extract Rust symbols."""
        from ..symbol_graph import Location, Reference, Symbol, SymbolKind

        root = tree.root_node
        count = 0
        current_module = ""  # Track current module path

        def process_node(node, parent_name: str = "", impl_target: str = ""):
            nonlocal count, current_module

            # Function: fn name() {}
            if node.type == "function_item":
                name_node = node.child_by_field_name("name")
                if name_node:
                    name = self._get_node_text(name_node, source)
                    location = self._get_location(node, file_path)

                    # Build qualified name
                    qualified_name = f"{current_module}::{name}" if current_module else name

                    # Get parameters
                    params_node = node.child_by_field_name("parameters")
                    params_text = ""
                    if params_node:
                        params_text = self._get_node_text(params_node, source)

                    # Get return type if present
                    return_type = ""
                    for child in node.children:
                        if child.type == "return_type":
                            return_type = self._get_node_text(child, source)
                            break

                    signature = f"fn {qualified_name}{params_text}{return_type}"

                    kind = SymbolKind.METHOD if impl_target else SymbolKind.FUNCTION

                    symbol = Symbol(
                        name=qualified_name,
                        kind=kind,
                        location=location,
                        signature=signature,
                        parent=impl_target if impl_target else parent_name if parent_name else None,
                    )
                    graph.add_symbol(symbol)

                    if impl_target:
                        ref = Reference(
                            source=impl_target,
                            target=qualified_name,
                            kind="impl",
                            location=location,
                        )
                        graph.add_reference(ref)
                    elif parent_name:
                        ref = Reference(
                            source=parent_name,
                            target=qualified_name,
                            kind="contains",
                            location=location,
                        )
                        graph.add_reference(ref)

                    count += 1

                    # Process function body
                    body_node = node.child_by_field_name("body")
                    if body_node:
                        for child in body_node.children:
                            process_node(child, qualified_name, "")

            # Struct: struct Name { ... }
            elif node.type == "struct_item":
                name_node = node.child_by_field_name("name")
                if name_node:
                    name = self._get_node_text(name_node, source)
                    location = self._get_location(node, file_path)

                    qualified_name = f"{current_module}::{name}" if current_module else name

                    # Get type parameters if any
                    type_params = ""
                    for child in node.children:
                        if child.type == "type_parameters":
                            type_params = self._get_node_text(child, source)
                            break

                    signature = f"struct {qualified_name}{type_params}"

                    symbol = Symbol(
                        name=qualified_name,
                        kind=SymbolKind.STRUCT,
                        location=location,
                        signature=signature,
                        parent=current_module if current_module else None,
                    )
                    graph.add_symbol(symbol)
                    count += 1

                    # Extract struct fields
                    body_node = node.child_by_field_name("body")
                    if body_node:
                        for child in body_node.children:
                            if child.type == "field_declaration":
                                self._extract_field(child, qualified_name, source, file_path, graph)

            # Enum: enum Name { ... }
            elif node.type == "enum_item":
                name_node = node.child_by_field_name("name")
                if name_node:
                    name = self._get_node_text(name_node, source)
                    location = self._get_location(node, file_path)

                    qualified_name = f"{current_module}::{name}" if current_module else name

                    # Get type parameters
                    type_params = ""
                    for child in node.children:
                        if child.type == "type_parameters":
                            type_params = self._get_node_text(child, source)
                            break

                    signature = f"enum {qualified_name}{type_params}"

                    symbol = Symbol(
                        name=qualified_name,
                        kind=SymbolKind.ENUM,
                        location=location,
                        signature=signature,
                        parent=current_module if current_module else None,
                    )
                    graph.add_symbol(symbol)
                    count += 1

                    # Extract enum variants
                    body_node = node.child_by_field_name("body")
                    if body_node:
                        for child in body_node.children:
                            if child.type == "variant":
                                variant_name_node = child.child_by_field_name("name")
                                if variant_name_node:
                                    variant_name = self._get_node_text(variant_name_node, source)
                                    variant_loc = self._get_location(child, file_path)
                                    variant_qualified = f"{qualified_name}::{variant_name}"

                                    variant_symbol = Symbol(
                                        name=variant_qualified,
                                        kind=SymbolKind.CONSTANT,
                                        location=variant_loc,
                                        parent=qualified_name,
                                    )
                                    graph.add_symbol(variant_symbol)

                                    ref = Reference(
                                        source=qualified_name,
                                        target=variant_qualified,
                                        kind="contains",
                                        location=variant_loc,
                                    )
                                    graph.add_reference(ref)

            # Trait: trait Name { ... }
            elif node.type == "trait_item":
                name_node = node.child_by_field_name("name")
                if name_node:
                    name = self._get_node_text(name_node, source)
                    location = self._get_location(node, file_path)

                    qualified_name = f"{current_module}::{name}" if current_module else name

                    # Get type parameters
                    type_params = ""
                    for child in node.children:
                        if child.type == "type_parameters":
                            type_params = self._get_node_text(child, source)
                            break

                    signature = f"trait {qualified_name}{type_params}"

                    symbol = Symbol(
                        name=qualified_name,
                        kind=SymbolKind.TRAIT,
                        location=location,
                        signature=signature,
                        parent=current_module if current_module else None,
                    )
                    graph.add_symbol(symbol)
                    count += 1

                    # Extract trait items
                    body_node = node.child_by_field_name("body")
                    if body_node:
                        for child in body_node.children:
                            if child.type == "function_item":
                                # Trait method
                                process_node(child, qualified_name, "")

            # Impl block: impl Target { ... } or impl Trait for Target { ... }
            elif node.type == "impl_item":
                impl_node = node.child_by_field_name("type")
                trait_node = node.child_by_field_name("trait")

                if impl_node:
                    impl_type = self._get_node_text(impl_node, source)

                    if trait_node:
                        trait_type = self._get_node_text(trait_node, source)
                        impl_target = f"{trait_type} for {impl_type}"
                    else:
                        impl_target = impl_type

                    # Process impl body
                    body_node = node.child_by_field_name("body")
                    if body_node:
                        for child in body_node.children:
                            process_node(child, parent_name, impl_target)

            # Module: mod name { ... } or mod name;
            elif node.type == "mod_item":
                name_node = node.child_by_field_name("name")
                if name_node:
                    name = self._get_node_text(name_node, source)
                    location = self._get_location(node, file_path)

                    old_module = current_module
                    current_module = f"{old_module}::{name}" if old_module else name

                    symbol = Symbol(
                        name=current_module,
                        kind=SymbolKind.MODULE,
                        location=location,
                        signature=f"mod {current_module}",
                        parent=old_module if old_module else None,
                    )
                    graph.add_symbol(symbol)
                    count += 1

                    # Process module body if inline
                    body_node = node.child_by_field_name("body")
                    if body_node:
                        for child in body_node.children:
                            process_node(child, current_module, "")

                    # Restore module context
                    current_module = old_module

            # Type alias: type Name = ...;
            elif node.type == "type_item":
                name_node = node.child_by_field_name("name")
                if name_node:
                    name = self._get_node_text(name_node, source)
                    location = self._get_location(node, file_path)

                    qualified_name = f"{current_module}::{name}" if current_module else name

                    # Get type value
                    type_node = node.child_by_field_name("type")
                    type_value = ""
                    if type_node:
                        type_value = self._get_node_text(type_node, source)

                    signature = f"type {qualified_name} = {type_value}"

                    symbol = Symbol(
                        name=qualified_name,
                        kind=SymbolKind.TYPE_ALIAS,
                        location=location,
                        signature=signature,
                        parent=current_module if current_module else None,
                    )
                    graph.add_symbol(symbol)
                    count += 1

            # Constant: const NAME: Type = value;
            elif node.type == "const_item":
                name_node = node.child_by_field_name("name")
                if name_node:
                    name = self._get_node_text(name_node, source)
                    location = self._get_location(node, file_path)

                    qualified_name = f"{current_module}::{name}" if current_module else name

                    # Get type
                    type_node = node.child_by_field_name("type")
                    type_text = ""
                    if type_node:
                        type_text = self._get_node_text(type_node, source)

                    symbol = Symbol(
                        name=qualified_name,
                        kind=SymbolKind.CONSTANT,
                        location=location,
                        signature=f"const {qualified_name}{type_text}",
                        parent=current_module if current_module else None,
                    )
                    graph.add_symbol(symbol)
                    count += 1

            # Static: static NAME: Type = value;
            elif node.type == "static_item":
                name_node = node.child_by_field_name("name")
                if name_node:
                    name = self._get_node_text(name_node, source)
                    location = self._get_location(node, file_path)

                    qualified_name = f"{currentmodule}::{name}" if current_module else name

                    type_node = node.child_by_field_name("type")
                    type_text = ""
                    if type_node:
                        type_text = self._get_node_text(type_node, source)

                    symbol = Symbol(
                        name=qualified_name,
                        kind=SymbolKind.VARIABLE,
                        location=location,
                        signature=f"static {qualified_name}{type_text}",
                        parent=current_module if current_module else None,
                    )
                    graph.add_symbol(symbol)
                    count += 1

            # Use statements (imports)
            elif node.type == "use_declaration":
                self._extract_use(node, source, file_path, graph, current_module)

            # Call expression
            elif node.type == "call_expression":
                self._extract_call(node, source, file_path, graph, parent_name)

            # Process children
            else:
                for child in node.children:
                    process_node(child, parent_name, impl_target)

        for child in root.children:
            process_node(child, "", "")

        return count

    def _extract_field(
        self,
        node,
        struct_name: str,
        source: str | bytes,
        file_path: str,
        graph: "SymbolGraph",
    ) -> None:
        """Extract a struct field."""
        from ..symbol_graph import Location, Reference, Symbol, SymbolKind

        name_node = node.child_by_field_name("name")
        if not name_node:
            return

        name = self._get_node_text(name_node, source)
        location = self._get_location(node, file_path)

        # Get type
        type_node = node.child_by_field_name("type")
        type_text = ""
        if type_node:
            type_text = self._get_node_text(type_node, source)

        signature = f"{name}: {type_text}"

        symbol = Symbol(
            name=f"{struct_name}.{name}",
            kind=SymbolKind.VARIABLE,
            location=location,
            signature=signature,
            parent=struct_name,
        )
        graph.add_symbol(symbol)

        ref = Reference(
            source=struct_name,
            target=f"{struct_name}.{name}",
            kind="contains",
            location=location,
        )
        graph.add_reference(ref)

    def _extract_use(
        self,
        node,
        source: str | bytes,
        file_path: str,
        graph: "SymbolGraph",
        current_module: str,
    ) -> None:
        """Extract use declaration (import)."""
        from ..symbol_graph import Location, Reference, Symbol, SymbolKind

        argument_node = node.child_by_field_name("argument")
        if not argument_node:
            return

        use_path = self._get_node_text(argument_node, source)
        location = self._get_location(node, file_path)

        # Create import symbol
        symbol = Symbol(
            name=use_path,
            kind=SymbolKind.IMPORT,
            location=location,
            signature=f"use {use_path};",
            parent=current_module if current_module else None,
        )
        graph.add_symbol(symbol)

        ref = Reference(
            source=current_module if current_module else "<module>",
            target=use_path,
            kind="import",
            location=location,
        )
        graph.add_reference(ref)

    def _extract_call(
        self,
        node,
        source: str | bytes,
        file_path: str,
        graph: "SymbolGraph",
        parent_name: str,
    ) -> None:
        """Extract function call reference."""
        from ..symbol_graph import Location, Reference

        if not parent_name:
            return

        function_node = node.child_by_field_name("function")
        if not function_node:
            return

        func_name = self._get_node_text(function_node, source)

        location = self._get_location(node, file_path)
        ref = Reference(
            source=parent_name,
            target=func_name,
            kind="call",
            location=location,
        )
        graph.add_reference(ref)
