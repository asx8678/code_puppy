"""Python AST extractor using Tree-sitter.

Extracts: functions, classes, methods, imports, and calls.
"""

from typing import TYPE_CHECKING

from .base import BaseExtractor

if TYPE_CHECKING:
    from tree_sitter import Tree

    from ..symbol_graph import Location, SymbolGraph


class PythonExtractor(BaseExtractor):
    """Extracts Python symbols from Tree-sitter AST."""

    def extract(
        self,
        tree: "Tree",
        source: str | bytes,
        file_path: str,
        graph: "SymbolGraph",
    ) -> int:
        """Extract Python symbols."""
        from ..symbol_graph import Location, Reference, Symbol, SymbolKind

        root = tree.root_node
        count = 0

        def process_node(node, parent_name: str = ""):
            nonlocal count

            # Function definition
            if node.type == "function_definition":
                name_node = node.child_by_field_name("name")
                if name_node:
                    name = self._get_node_text(name_node, source)
                    location = self._get_location(node, file_path)

                    # Build signature
                    params_node = node.child_by_field_name("parameters")
                    params_text = ""
                    if params_node:
                        params_text = self._get_node_text(params_node, source)

                    signature = f"def {name}{params_text}"

                    # Get docstring
                    docstring = self._extract_docstring(node, source)

                    # Determine kind (method vs function)
                    kind = SymbolKind.METHOD if parent_name else SymbolKind.FUNCTION

                    symbol = Symbol(
                        name=name,
                        kind=kind,
                        location=location,
                        signature=signature,
                        docstring=docstring,
                        parent=parent_name if parent_name else None,
                    )
                    graph.add_symbol(symbol)

                    # Add reference from parent if applicable
                    if parent_name:
                        ref = Reference(
                            source=parent_name,
                            target=name,
                            kind="contains",
                            location=location,
                        )
                        graph.add_reference(ref)

                    count += 1

                    # Process children with this as parent
                    for child in node.children:
                        process_node(child, name)

            # Class definition
            elif node.type == "class_definition":
                name_node = node.child_by_field_name("name")
                if name_node:
                    name = self._get_node_text(name_node, source)
                    location = self._get_location(node, file_path)

                    # Get inheritance
                    bases_node = node.child_by_field_name("bases")
                    bases_text = ""
                    if bases_node:
                        bases_text = self._get_node_text(bases_node, source)

                    signature = f"class {name}{bases_text}"

                    # Get docstring
                    docstring = self._extract_docstring(node, source)

                    symbol = Symbol(
                        name=name,
                        kind=SymbolKind.CLASS,
                        location=location,
                        signature=signature,
                        docstring=docstring,
                        parent=parent_name if parent_name else None,
                    )
                    graph.add_symbol(symbol)

                    # Add inheritance references
                    if bases_node:
                        for base in bases_node.children:
                            if base.type in ("identifier", "attribute"):
                                base_name = self._get_node_text(base, source)
                                ref = Reference(
                                    source=name,
                                    target=base_name,
                                    kind="inheritance",
                                    location=location,
                                )
                                graph.add_reference(ref)

                    count += 1

                    # Process children with this as parent
                    for child in node.children:
                        process_node(child, name)

            # Import statements
            elif node.type in ("import_statement", "import_from_statement"):
                self._extract_import(node, source, file_path, graph)

            # Call expressions (function calls)
            elif node.type == "call":
                self._extract_call(node, source, file_path, graph, parent_name)

            # Process other children
            else:
                for child in node.children:
                    process_node(child, parent_name)

        # Start processing from root
        for child in root.children:
            process_node(child, "")

        return count

    def _extract_docstring(self, node, source: str | bytes) -> str:
        """Extract docstring from function/class body."""
        body_node = node.child_by_field_name("body")
        if not body_node or not body_node.children:
            return ""

        # First child might be an expression_statement with a string
        first = body_node.children[0]
        if first.type == "expression_statement":
            string_node = first.children[0] if first.children else None
            if string_node and string_node.type in (
                "string",
                "string_content",
                "string_literal",
            ):
                text = self._get_node_text(string_node, source)
                # Clean up quotes
                return text.strip('"\'\n\r ')

        return ""

    def _extract_import(
        self,
        node,
        source: str | bytes,
        file_path: str,
        graph: "SymbolGraph",
    ) -> None:
        """Extract import statement as a symbol."""
        from ..symbol_graph import Location, Reference, Symbol, SymbolKind

        location = self._get_location(node, file_path)

        if node.type == "import_statement":
            # import x, y, z
            for child in node.children:
                if child.type == "dotted_name" or child.type == "identifier":
                    name = self._get_node_text(child, source)
                    symbol = Symbol(
                        name=name,
                        kind=SymbolKind.IMPORT,
                        location=location,
                    )
                    graph.add_symbol(symbol)

                    # Reference to the imported module
                    ref = Reference(
                        source="<module>",
                        target=name,
                        kind="import",
                        location=location,
                    )
                    graph.add_reference(ref)

        elif node.type == "import_from_statement":
            # from x import y, z
            module_node = node.child_by_field_name("module")
            if module_node:
                module_name = self._get_node_text(module_node, source)

                # Find imported names
                for child in node.children:
                    if child.type == "import_list" or child.type == "aliased_imports":
                        for imported in child.children:
                            if imported.type in ("identifier", "aliased_import"):
                                if imported.type == "aliased_import":
                                    name_node = imported.child_by_field_name("name")
                                    name = (
                                        self._get_node_text(name_node, source)
                                        if name_node
                                        else ""
                                    )
                                else:
                                    name = self._get_node_text(imported, source)

                                full_name = f"{module_name}.{name}"
                                symbol = Symbol(
                                    name=full_name,
                                    kind=SymbolKind.IMPORT,
                                    location=location,
                                )
                                graph.add_symbol(symbol)

                                ref = Reference(
                                    source="<module>",
                                    target=full_name,
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
        """Extract function call as a reference."""
        from ..symbol_graph import Location, Reference

        function_node = node.child_by_field_name("function")
        if not function_node:
            return

        # Get the function name
        func_name = ""
        if function_node.type == "identifier":
            func_name = self._get_node_text(function_node, source)
        elif function_node.type == "attribute":
            # Method call: obj.method()
            func_name = self._get_node_text(function_node, source)

        if func_name and parent_name:
            location = self._get_location(node, file_path)
            ref = Reference(
                source=parent_name,
                target=func_name,
                kind="call",
                location=location,
            )
            graph.add_reference(ref)
