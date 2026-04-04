"""JavaScript AST extractor using Tree-sitter.

Extracts: functions, classes, methods, imports, exports, and calls.
"""

from typing import TYPE_CHECKING

from .base import BaseExtractor

if TYPE_CHECKING:
    from tree_sitter import Tree

    from ..symbol_graph import SymbolGraph


class JavaScriptExtractor(BaseExtractor):
    """Extracts JavaScript symbols from Tree-sitter AST."""

    def extract(
        self,
        tree: "Tree",
        source: str | bytes,
        file_path: str,
        graph: "SymbolGraph",
    ) -> int:
        """Extract JavaScript symbols."""
        from ..symbol_graph import Location, Reference, Symbol, SymbolKind

        root = tree.root_node
        count = 0

        def process_node(node, parent_name: str = "", class_name: str = ""):
            nonlocal count

            # Function declaration: function name() {}
            if node.type == "function_declaration":
                name_node = node.child_by_field_name("name")
                if name_node:
                    name = self._get_node_text(name_node, source)
                    location = self._get_location(node, file_path)

                    # Get parameters
                    params_node = node.child_by_field_name("parameters")
                    params_text = ""
                    if params_node:
                        params_text = self._get_node_text(params_node, source)

                    signature = f"function {name}{params_text}"

                    kind = SymbolKind.METHOD if class_name else SymbolKind.FUNCTION

                    symbol = Symbol(
                        name=name,
                        kind=kind,
                        location=location,
                        signature=signature,
                        parent=class_name if class_name else parent_name if parent_name else None,
                    )
                    graph.add_symbol(symbol)

                    if class_name or parent_name:
                        ref = Reference(
                            source=class_name or parent_name,
                            target=name,
                            kind="contains",
                            location=location,
                        )
                        graph.add_reference(ref)

                    count += 1

                    # Process children with this as parent
                    for child in node.children:
                        process_node(child, name, class_name)

            # Function expression (assigned to variable)
            elif node.type == "function_expression":
                # Check if this is assigned to something
                # We process this when we see the parent assignment
                for child in node.children:
                    process_node(child, parent_name, class_name)

            # Arrow function
            elif node.type == "arrow_function":
                # Process children
                for child in node.children:
                    process_node(child, parent_name, class_name)

            # Class declaration: class Name {}
            elif node.type == "class_declaration":
                name_node = node.child_by_field_name("name")
                if name_node:
                    name = self._get_node_text(name_node, source)
                    location = self._get_location(node, file_path)

                    # Get superclass
                    superclass_node = node.child_by_field_name("superclass")
                    extends_text = ""
                    if superclass_node:
                        extends_text = self._get_node_text(superclass_node, source)
                        # Add inheritance reference
                        ref = Reference(
                            source=name,
                            target=extends_text,
                            kind="inheritance",
                            location=location,
                        )
                        graph.add_reference(ref)

                    signature = f"class {name} extends {extends_text}" if extends_text else f"class {name}"

                    symbol = Symbol(
                        name=name,
                        kind=SymbolKind.CLASS,
                        location=location,
                        signature=signature,
                    )
                    graph.add_symbol(symbol)
                    count += 1

                    # Process body with class name
                    body_node = node.child_by_field_name("body")
                    if body_node:
                        for child in body_node.children:
                            process_node(child, name, name)

            # Method definition in class
            elif node.type == "method_definition":
                name_node = node.child_by_field_name("name")
                if name_node:
                    name = self._get_node_text(name_node, source)
                    location = self._get_location(node, file_path)

                    # Check if it's static, async, etc.
                    modifiers = []
                    if any(child.type == "static" for child in node.children):
                        modifiers.append("static")
                    if any(child.type == "async" for child in node.children):
                        modifiers.append("async")
                    if any(child.type == "get" for child in node.children):
                        modifiers.append("get")
                    if any(child.type == "set" for child in node.children):
                        modifiers.append("set")

                    params_node = node.child_by_field_name("parameters")
                    params_text = ""
                    if params_node:
                        params_text = self._get_node_text(params_node, source)

                    mod_str = " ".join(modifiers) + " " if modifiers else ""
                    signature = f"{mod_str}{name}{params_text}"

                    kind = SymbolKind.METHOD

                    symbol = Symbol(
                        name=name,
                        kind=kind,
                        location=location,
                        signature=signature,
                        parent=class_name if class_name else None,
                    )
                    graph.add_symbol(symbol)

                    if class_name:
                        ref = Reference(
                            source=class_name,
                            target=name,
                            kind="contains",
                            location=location,
                        )
                        graph.add_reference(ref)

                    count += 1

                    # Process method body
                    for child in node.children:
                        process_node(child, name, class_name)

            # Variable declaration (const, let, var)
            elif node.type == "variable_declaration":
                for child in node.children:
                    if child.type == "variable_declarator":
                        name_node = child.child_by_field_name("name")
                        value_node = child.child_by_field_name("value")

                        if name_node:
                            name = self._get_node_text(name_node, source)
                            location = self._get_location(child, file_path)

                            # Check if it's a function assignment
                            is_function = value_node and value_node.type in (
                                "function_expression",
                                "arrow_function",
                            )

                            if is_function:
                                kind = SymbolKind.FUNCTION
                                signature = f"function {name}()"
                            else:
                                kind = SymbolKind.VARIABLE
                                signature = name

                            symbol = Symbol(
                                name=name,
                                kind=kind,
                                location=location,
                                signature=signature,
                                parent=parent_name if parent_name else None,
                            )
                            graph.add_symbol(symbol)

                            if parent_name:
                                ref = Reference(
                                    source=parent_name,
                                    target=name,
                                    kind="contains",
                                    location=location,
                                )
                                graph.add_reference(ref)

                            count += 1

                            # Process value if it's a function
                            if value_node:
                                for val_child in value_node.children:
                                    process_node(val_child, name, class_name)

            # Import statements
            elif node.type == "import_statement":
                self._extract_import(node, source, file_path, graph)

            # Export statement
            elif node.type == "export_statement":
                # Check if it exports a declaration
                declaration = node.child_by_field_name("declaration")
                if declaration:
                    process_node(declaration, parent_name, class_name)

            # Call expression
            elif node.type == "call_expression":
                self._extract_call(node, source, file_path, graph, parent_name or class_name)

            # Process other children
            else:
                for child in node.children:
                    process_node(child, parent_name, class_name)

        for child in root.children:
            process_node(child, "", "")

        return count

    def _extract_import(
        self,
        node,
        source: str | bytes,
        file_path: str,
        graph: "SymbolGraph",
    ) -> None:
        """Extract import statement."""
        from ..symbol_graph import Location, Reference, Symbol, SymbolKind

        location = self._get_location(node, file_path)

        # import { a, b } from 'module'
        # import * as name from 'module'
        # import name from 'module'
        # import 'module'

        source_node = None
        for child in node.children:
            if child.type == "string":
                source_node = child
                break

        if source_node:
            module_name = self._get_node_text(source_node, source).strip("'\"")

            # Find imported names
            for child in node.children:
                if child.type == "import_clause":
                    for imported in child.children:
                        if imported.type == "identifier":
                            name = self._get_node_text(imported, source)
                            symbol = Symbol(
                                name=name,
                                kind=SymbolKind.IMPORT,
                                location=location,
                                signature=f"import {{ {name} }} from '{module_name}'",
                            )
                            graph.add_symbol(symbol)

                            ref = Reference(
                                source="<module>",
                                target=name,
                                kind="import",
                                location=location,
                            )
                            graph.add_reference(ref)

                        elif imported.type == "named_imports":
                            for specifier in imported.children:
                                if specifier.type == "import_specifier":
                                    name_node = specifier.child_by_field_name("name")
                                    if name_node:
                                        name = self._get_node_text(name_node, source)
                                        symbol = Symbol(
                                            name=name,
                                            kind=SymbolKind.IMPORT,
                                            location=location,
                                            signature=f"import {{ {name} }} from '{module_name}'",
                                        )
                                        graph.add_symbol(symbol)

    def _extract_call(
        self,
        node,
        source: str | bytes,
        file_path: str,
        graph: "SymbolGraph",
        parent_name: str,
    ) -> None:
        """Extract function call."""
        from ..symbol_graph import Location, Reference

        if not parent_name:
            return

        function_node = node.child_by_field_name("function")
        if not function_node:
            return

        func_name = ""
        if function_node.type == "identifier":
            func_name = self._get_node_text(function_node, source)
        elif function_node.type == "member_expression":
            func_name = self._get_node_text(function_node, source)

        if func_name:
            location = self._get_location(node, file_path)
            ref = Reference(
                source=parent_name,
                target=func_name,
                kind="call",
                location=location,
            )
            graph.add_reference(ref)
