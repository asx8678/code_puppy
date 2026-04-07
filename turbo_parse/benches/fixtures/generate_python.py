#!/usr/bin/env python3
"""Generate Python test fixtures of various sizes."""

import sys
from pathlib import Path


def generate_function(index: int, complexity: str = "medium") -> str:
    """Generate a Python function with realistic code."""
    if complexity == "simple":
        return f'''def func_{index}(x: int) -> int:
    """Simple function {index}."""
    return x * {index}

'''
    elif complexity == "medium":
        return f'''def process_data_{index}(data: list[dict]) -> dict:
    """Process data batch {index} with filtering and aggregation."""
    result = {{}}
    total = 0
    for item in data:
        if item.get("active", False):
            key = item.get("category", "unknown")
            value = item.get("amount", 0)
            if key not in result:
                result[key] = 0
            result[key] += value
            total += value
    result["_total"] = total
    return result

'''
    else:  # complex
        return f'''class DataProcessor{index}:
    """Data processor class {index} with multiple methods."""
    
    def __init__(self, config: dict):
        self.config = config
        self.cache = {{}}
        self.metrics = {{"calls": 0, "errors": 0}}
    
    def process(self, data: list[dict]) -> list[dict]:
        """Process batch of data items."""
        self.metrics["calls"] += 1
        results = []
        for item in data:
            try:
                if self._validate(item):
                    processed = self._transform(item)
                    results.append(processed)
            except ValueError as e:
                self.metrics["errors"] += 1
                self._log_error(e, item)
        return results
    
    def _validate(self, item: dict) -> bool:
        """Validate data item structure."""
        required = ["id", "value"]
        return all(k in item for k in required)
    
    def _transform(self, item: dict) -> dict:
        """Transform data item."""
        cache_key = item["id"]
        if cache_key in self.cache:
            return self.cache[cache_key]
        
        result = {{
            "id": item["id"],
            "value": item["value"] * 2,
            "timestamp": item.get("timestamp"),
            "processed": True,
        }}
        self.cache[cache_key] = result
        return result
    
    def _log_error(self, error: Exception, item: dict) -> None:
        """Log processing error."""
        print(f"Error processing {{item.get('id')}}: {{error}}")

'''


def generate_imports() -> str:
    """Generate realistic Python imports."""
    return '''"""Large Python module for benchmark testing."""

from __future__ import annotations

import abc
import asyncio
import collections
import dataclasses
import enum
import functools
import hashlib
import io
import json
import logging
import os
import re
import sys
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum, auto
from pathlib import Path
from typing import Any, Generic, TypeVar, Union, Optional

import numpy as np  # type: ignore
import pandas as pd  # type: ignore
import requests

T = TypeVar("T")

'''


def generate_fixture(target_lines: int, output_path: Path) -> None:
    """Generate a Python file with approximately target_lines lines of code."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    lines_written = 0
    functions_written = 0
    
    with open(output_path, "w") as f:
        # Write imports (approx 25 lines)
        imports = generate_imports()
        f.write(imports)
        lines_written += len(imports.split("\n"))
        
        # Mix of function complexities to simulate real codebase
        while lines_written < target_lines:
            # Progress from simple to complex as file grows
            if functions_written < target_lines // 50:
                complexity = "simple"
            elif functions_written < target_lines // 20:
                complexity = "medium"
            else:
                complexity = "complex"
            
            func_code = generate_function(functions_written, complexity)
            f.write(func_code)
            lines_written += len(func_code.split("\n"))
            functions_written += 1
            
            # Add occasional blank lines and comments (5% chance)
            if functions_written % 20 == 0:
                comment = f"\n# Section {{functions_written // 20}}\n\n"
                f.write(comment)
                lines_written += len(comment.split("\n"))
    
    # Count actual lines
    with open(output_path) as f:
        actual_lines = len(f.readlines())
    
    print(f"Generated {output_path}: {actual_lines} lines (target: {target_lines})")
    return actual_lines


def main():
    """Generate all Python fixtures."""
    base_dir = Path(__file__).parent / "python"
    
    # Generate 1k LOC
    generate_fixture(1000, base_dir / "sample_1k.py")
    
    # Generate 10k LOC
    generate_fixture(10000, base_dir / "sample_10k.py")
    
    # Generate 100k LOC
    generate_fixture(100000, base_dir / "sample_100k.py")
    
    print("Python fixtures generated successfully!")


if __name__ == "__main__":
    main()
