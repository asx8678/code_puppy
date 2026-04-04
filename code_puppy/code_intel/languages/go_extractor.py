"""Go AST extractor using Tree-sitter.

Extracts: functions, methods, structs, interfaces, types, imports, and calls.
"""

from typing import TYPE_CHECKING

from .base import BaseExtractor

if TYPE_CHECKING:
    from tree_sitter import Tree

    from ..symbol_graph import SymbolGraph


class GoExtractor(BaseExtractor):
    """Extracts Go symbols from Tree-sitter AST."""

    def extract(
        self,
        tree: "Tree",
        source: str | bytes,
        file_path: str,
        graph: "SymbolGraph",
    ) -> int:
        """Extract Go symbols."""
        from ..symbol_graph import Location, Reference, Symbol, SymbolKind

        root = tree.root_node
        count = 0
        current_package = ""  # Track package name

        def process_node(node, parent_name: str = "", receiver_type: str = ""):
            nonlocal count, current_package

            # Package declaration: package name
            if node.type == "package_clause":
                name_node = node.child_by_field_name("name")
                if name_node:
                    current_package = self._get_node_text(name_node, source)
                    location = self._get_location(node, file_path)

                    symbol = Symbol(
                        name=current_package,
                        kind=SymbolKind.MODULE,
                        location=location,
                        signature=f"package {current_package}",
                    )
                    graph.add_symbol(symbol)
                    count += 1

            # Function declaration: func name() {}
            elif node.type == "function_declaration":
                name_node = node.child_by_field_name("name")
                if name_node:
                    name = self._get_node_text(name_node, source)
                    location = self._get_location(node, file_path)

                    # Get parameters
                    params_node = node.child_by_field_name("parameters")
                    params_text = ""
                    if params_node:
                        params_text = self._get_node_text(params_node, source)

                    # Get return type
                    result_node = node.child_by_field_name("result")
                    result_text = ""
                    if result_node:
                        result_text = self._get_node_text(result_node, source)

                    # Build signature
                    if receiver_type:
                        # Method: func (r Receiver) Name()
                        signature = f"func ({receiver_type}) {name}{params_text}{result_text}"
                        kind = SymbolKind.METHOD
                    else:
                        signature = f"func {name}{params_text}{result_text}"
                        kind = SymbolKind.FUNCTION

                    qualified_name = f"{current_package}.{name}" if current_package else name

                    symbol = Symbol(
                        name=qualified_name,
                        kind=kind,
                        location=location,
                        signature=signature,
                        parent=current_package if current_package else None,
                    )
                    graph.add_symbol(symbol)
                    count += 1

                    # Process function body
                    body_node = node.child_by_field_name("body")
                    if body_node:
                        for child in body_node.children:
                            process_node(child, qualified_name, "")

            # Method declaration (treated as function with receiver)
            # In Go tree-sitter, methods are function_declaration with receiver
            elif node.type == "method_declaration":
                name_node = node.child_by_field_name("name")
                recv_node = node.child_by_field_name("receiver")

                if name_node:
                    name = self._get_node_text(name_node, source)
                    location = self._get_location(node, file_path)

                    # Get receiver type
                    recv_type = ""
                    if recv_node:
                        recv_type = self._extract_receiver_type(recv_node, source)

                    params_node = node.child_by_field_name("parameters")
                    params_text = ""
                    if params_node:
                        params_text = self._get_node_text(params_node, source)

                    result_node = node.child_by_field_name("result")
                    result_text = ""
                    if result_node:
                        result_text = self._get_node_text(result_node, source)

                    signature = f"func ({recv_type}) {name}{params_text}{result_text}"
                    qualified_name = f"{current_package}.{name}" if current_package else name

                    symbol = Symbol(
                        name=qualified_name,
                        kind=SymbolKind.METHOD,
                        location=location,
                        signature=signature,
                        parent=recv_type if recv_type else current_package,
                    )
                    graph.add_symbol(symbol)

                    if recv_type:
                        ref = Reference(
                            source=recv_type,
                            target=qualified_name,
                            kind="method",
                            location=location,
                        )
                        graph.add_reference(ref)

                    count += 1

                    # Process method body
                    body_node = node.child_by_field_name("body")
                    if body_node:
                        for child in body_node.children:
                            process_node(child, qualified_name, "")

            # Type declaration: type Name ...
            elif node.type == "type_declaration":
                for child in node.children:
                    if child.type == "type_spec":
                        name_node = child.child_by_field_name("name")
                        type_node = child.child_by_field_name("type")

                        if name_node and type_node:
                            name = self._get_node_text(name_node, source)
                            location = self._get_location(child, file_path)

                            type_value = self._get_node_text(type_node, source)
                            qualified_name = f"{current_package}.{name}" if current_package else name

                            # Determine kind based on type
                            kind = SymbolKind.TYPE_ALIAS
                            if type_node.type == "struct_type":
                                kind = SymbolKind.STRUCT
                                signature = f"type {qualified_name} struct"
                            elif type_node.type == "interface_type":
                                kind = SymbolKind.INTERFACE
                                signature = f"type {qualified_name} interface"
                            else:
                                signature = f"type {qualified_name} = {type_value}"

                            symbol = Symbol(
                                name=qualified_name,
                                kind=kind,
                                location=location,
                                signature=signature,
                                parent=current_package if current_package else None,
                            )
                            graph.add_symbol(symbol)
                            count += 1

                            # Extract struct fields
                            if type_node.type == "struct_type":
                                for field in type_node.children:
                                    if field.type == "field_declaration_list":
                                        for f in field.children:
                                            if f.type == "field_declaration":
                                                self._extract_field(f, qualified_name, source, file_path, graph)

                            # Extract interface methods
                            elif type_node.type == "interface_type":
                                for method in type_node.children:
                                    if method.type == "method_spec":
                                        self._extract_interface_method(method, qualified_name, source, file_path, graph)

            # Import declaration
            elif node.type == "import_declaration":
                self._extract_import(node, source, file_path, graph, current_package)

            # Const declaration: const Name = value
            elif node.type == "const_declaration":
                for child in node.children:
                    if child.type == "const_spec":
                        name_node = child.child_by_field_name("name")
                        if name_node:
                            name = self._get_node_text(name_node, source)
                            location = self._get_location(child, file_path)
                            qualified_name = f"{current_package}.{name}" if current_package else name

                            # Get type if present
                            type_node = child.child_by_field_name("type")
                            type_text = ""
                            if type_node:
                                type_text = self._get_node_text(type_node, source)

                            value_node = child.child_by_field_name("value")
                            value_text = ""
                            if value_node:
                                value_text = self._get_node_text(value_node, source)

                            symbol = Symbol(
                                name=qualified_name,
                                kind=SymbolKind.CONSTANT,
                                location=location,
                                signature=f"const {qualified_name}{type_text} = {value_text}",
                                parent=current_package if current_package else None,
                            )
                            graph.add_symbol(symbol)
                            count += 1

            # Var declaration: var Name = value
            elif node.type == "var_declaration":
                for child in node.children:
                    if child.type == "var_spec":
                        name_node = child.child_by_field_name("name")
                        if name_node:
                            name = self._get_node_text(name_node, source)
                            location = self._get_location(child, file_path)
                            qualified_name = f"{current_package}.{name}" if current_package else name

                            type_node = child.child_by_field_name("type")
                            type_text = ""
                            if type_node:
                                type_text = self._get_node_text(type_node, source)

                            symbol = Symbol(
                                name=qualified_name,
                                kind=SymbolKind.VARIABLE,
                                location=location,
                                signature=f"var {qualified_name}{type_text}",
                                parent=current_package if current_package else None,
                            )
                            graph.add_symbol(symbol)
                            count += 1

            # Call expression
            elif node.type == "call_expression":
                self._extract_call(node, source, file_path, graph, parent_name)

            # Process children
            else:
                for child in node.children:
                    process_node(child, parent_name, receiver_type)

        for child in root.children:
            process_node(child, "", "")

        return count

    def _extract_receiver_type(self, recv_node, source: str | bytes) -> str:
        """Extract the type from a receiver node."""
        # Receiver has: parameters -> parameter_list -> parameter_declaration -> type_identifier
        for child in recv_node.children:
            if child.type == "parameter_list":
                for param in child.children:
                    if param.type == "parameter_declaration":
                        type_node = param.child_by_field_name("type")
                        if type_node:
                            return self._get_node_text(type_node, source)
        return ""

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

        # Get field names (can be multiple in one declaration)
        names = []
        type_node = None

        for child in node.children:
            if child.type == "field_identifier":
                names.append(self._get_node_text(child, source))
            elif child.type == "type":
                type_node = child

        if not names or not type_node:
            return

        type_text = self._get_node_text(type_node, source)

        for name in names:
            location = self._get_location(node, file_path)

            symbol = Symbol(
                name=f"{struct_name}.{name}",
                kind=SymbolKind.VARIABLE,
                location=location,
                signature=f"{name} {type_text}",
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

    def _extract_interface_method(
        self,
        node,
        interface_name: str,
        source: str | bytes,
        file_path: str,
        graph: "SymbolGraph",
    ) -> None:
        """Extract an interface method spec."""
        from ..symbol_graph import Location, Reference, Symbol, SymbolKind

        name_node = node.child_by_field_name("name")
        if not name_node:
            return

        name = self._get_node_text(name_node, source)
        location = self._get_location(node, file_path)

        # Get parameters
        params_node = node.child_by_field_name("parameters")
        params_text = ""
        if params_node:
            params_text = self._get_node_text(params_node, source)

        # Get return type
        result_node = node.child_by_field_name("result")
        result_text = ""
        if result_node:
            result_text = self._get_node_text(result_node, source)

        signature = f"{name}{params_text}{result_text}"

        symbol = Symbol(
            name=f"{interface_name}.{name}",
            kind=SymbolKind.METHOD,
            location=location,
            signature=signature,
            parent=interface_name,
        )
        graph.add_symbol(symbol)

        ref = Reference(
            source=interface_name,
            target=f"{interface_name}.{name}",
            kind="contains",
            location=location,
        )
        graph.add_reference(ref)

    def _extract_import(
        self,
        node,
        source: str | bytes,
        file_path: str,
        graph: "SymbolGraph",
        current_package: str,
    ) -> None:
        """Extract import statement."""
        from ..symbol_graph import Location, Reference, Symbol, SymbolKind

        # Import can have import_spec_list or single import_spec
        for child in node.children:
            if child.type == "import_spec_list":
                for spec in child.children:
                    if spec.type == "import_spec":
                        self._extract_import_spec(spec, source, file_path, graph, current_package)
            elif child.type == "import_spec":
                self._extract_import_spec(child, source, file_path, graph, current_package)

    def _extract_import_spec(
        self,
        node,
        source: str | bytes,
        file_path: str,
        graph: "SymbolGraph",
        current_package: str,
    ) -> None:
        """Extract a single import spec."""
        from ..symbol_graph import Location, Reference, Symbol, SymbolKind

        path_node = node.child_by_field_name("path")
        name_node = node.child_by_field_name("name")

        if not path_node:
            return

        import_path = self._get_node_text(path_node, source).strip('"')
        location = self._get_location(node, file_path)

        # Get alias if present
        alias = ""
        if name_node:
            alias = self._get_node_text(name_node, source)
            name = alias
        else:
            # Use last part of path as name
            name = import_path.split("/")[-1]

        symbol = Symbol(
            name=name,
            kind=SymbolKind.IMPORT,
            location=location,
            signature=f'import "{import_path}"',
            parent=current_package if current_package else None,
        )
        graph.add_symbol(symbol)

        ref = Reference(
            source=current_package if current_package else "<module>",
            target=name,
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
