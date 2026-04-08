#!/usr/bin/env python3
"""Generate JavaScript test fixtures of various sizes."""

from pathlib import Path


def generate_function(index: int, complexity: str = "medium") -> str:
    """Generate a JavaScript function with realistic code."""
    if complexity == "simple":
        return f"""/**
 * Simple function {index}
 * @param {{number}} x - Input value
 * @returns {{number}} - Result
 */
function func_{index}(x) {{
    return x * {index};
}}

"""
    elif complexity == "medium":
        return f"""/**
 * Data processor {index}
 * @param {{Array<Object>}} data - Data to process
 * @param {{Function}} filterFn - Filter function
 * @returns {{Object}} - Aggregated results
 */
function processData_{index}(data, filterFn) {{
    const results = {{}};
    let total = 0;
    
    for (const item of data) {{
        if (filterFn && !filterFn(item)) continue;
        
        const key = item.category || 'unknown';
        const value = item.amount || 0;
        
        if (!results[key]) {{
            results[key] = 0;
        }}
        results[key] += value;
        total += value;
    }}
    
    results._total = total;
    results._count = data.length;
    return results;
}}

"""
    else:  # complex
        return f"""/**
 * DataProcessor class {index}
 */
class DataProcessor{index} {{
    /**
     * @param {{Object}} config - Configuration object
     */
    constructor(config = {{}}) {{
        this.config = {{
            batchSize: config.batchSize || 100,
            timeout: config.timeout || 5000,
            enableCache: config.enableCache !== false,
        }};
        this.cache = new Map();
        this.metrics = {{ calls: 0, errors: 0, cacheHits: 0 }};
        this.listeners = new Map();
    }}

    /**
     * Process batch of data
     * @param {{Array<Object>}} data - Data items to process
     * @returns {{Array<Object>}} - Processed items
     */
    process(data) {{
        this.metrics.calls++;
        const results = [];
        
        for (const item of data) {{
            try {{
                if (this._validate(item)) {{
                    const processed = this._transform(item);
                    results.push(processed);
                }}
            }} catch (error) {{
                this.metrics.errors++;
                this._emit('error', {{ error, item }});
                this._logError(error, item);
            }}
        }}
        
        this._emit('complete', {{ count: results.length }});
        return results;
    }}

    /**
     * Validate data item
     * @private
     * @param {{Object}} item - Item to validate
     * @returns {{boolean}} - True if valid
     */
    _validate(item) {{
        return item && typeof item.id !== 'undefined' && 'value' in item;
    }}

    /**
     * Transform data item
     * @private
     * @param {{Object}} item - Item to transform
     * @returns {{Object}} - Transformed item
     */
    _transform(item) {{
        const cacheKey = item.id;
        
        if (this.config.enableCache && this.cache.has(cacheKey)) {{
            this.metrics.cacheHits++;
            return this.cache.get(cacheKey);
        }}
        
        const result = {{
            id: item.id,
            value: item.value * 2,
            timestamp: item.timestamp || Date.now(),
            processed: true,
            processor: {index},
        }};
        
        if (this.config.enableCache) {{
            this.cache.set(cacheKey, result);
        }}
        
        return result;
    }}

    /**
     * Log error
     * @private
     * @param {{Error}} error - Error object
     * @param {{Object}} item - Related item
     */
    _logError(error, item) {{
        console.error(`Error processing ${{item.id}}: ${{error.message}}`);
    }}

    /**
     * Emit event
     * @private
     * @param {{string}} event - Event name
     * @param {{Object}} data - Event data
     */
    _emit(event, data) {{
        const listeners = this.listeners.get(event) || [];
        listeners.forEach(fn => {{
            try {{
                fn(data);
            }} catch (e) {{
                console.error('Listener error:', e);
            }}
        }});
    }}

    /**
     * Add event listener
     * @param {{string}} event - Event name
     * @param {{Function}} fn - Callback function
     */
    on(event, fn) {{
        if (!this.listeners.has(event)) {{
            this.listeners.set(event, []);
        }}
        this.listeners.get(event).push(fn);
    }}

    /**
     * Get metrics
     * @returns {{Object}} - Current metrics
     */
    getMetrics() {{
        return {{ ...this.metrics }};
    }}
}}

"""


def generate_imports() -> str:
    """Generate realistic JavaScript imports."""
    return """/**
 * Large JavaScript module for benchmark testing
 * @module benchmark-sample
 */

'use strict';

const fs = require('fs');
const path = require('path');
const util = require('util');
const crypto = require('crypto');
const events = require('events');
const stream = require('stream');
const http = require('http');
const url = require('url');

const axios = require('axios');
const lodash = require('lodash');
const moment = require('moment');

const readFileAsync = util.promisify(fs.readFile);
const writeFileAsync = util.promisify(fs.writeFile);

/**
 * Module version
 * @type {{string}}
 */
const VERSION = '1.0.0';

/**
 * Default configuration
 * @type {{Object}}
 */
const DEFAULT_CONFIG = {{
    maxBatchSize: 1000,
    timeout: 30000,
    retries: 3,
}};

module.exports = {{ VERSION, DEFAULT_CONFIG }};

"""


def generate_fixture(target_lines: int, output_path: Path) -> int:
    """Generate a JavaScript file with approximately target_lines lines of code."""
    output_path.parent.mkdir(parents=True, exist_ok=True)

    lines_written = 0
    functions_written = 0

    with open(output_path, "w") as f:
        # Write imports (approx 30 lines)
        imports = generate_imports()
        f.write(imports)
        lines_written += len(imports.split("\n"))

        # Mix of function complexities
        while lines_written < target_lines:
            # Vary complexity based on progress
            if functions_written < target_lines // 30:
                complexity = "simple"
            elif functions_written < target_lines // 12:
                complexity = "medium"
            else:
                complexity = "complex"

            func_code = generate_function(functions_written, complexity)
            f.write(func_code)
            lines_written += len(func_code.split("\n"))
            functions_written += 1

            # Add occasional utilities and constants
            if functions_written % 15 == 0:
                util_code = f"""// Utility set {{functions_written // 15}}
const CONSTANTS_{functions_written // 15} = {{
    MAX_SIZE: {functions_written * 100},
    TIMEOUT: {functions_written * 1000},
    RETRY_COUNT: 3,
}};

/**
 * Utility function for batch {{functions_written // 15}}
 * @param {{Array}} arr - Input array
 * @returns {{Array}} - Transformed array
 */
const util_{functions_written // 15} = (arr) => arr.map(x => x * 2).filter(x => x > 0);

"""
                f.write(util_code)
                lines_written += len(util_code.split("\n"))

    # Count actual lines
    with open(output_path) as f:
        actual_lines = len(f.readlines())

    print(f"Generated {output_path}: {actual_lines} lines (target: {target_lines})")
    return actual_lines


def main():
    """Generate all JavaScript fixtures."""
    base_dir = Path(__file__).parent / "javascript"

    # Generate 1k LOC
    generate_fixture(1000, base_dir / "sample_1k.js")

    # Generate 10k LOC
    generate_fixture(10000, base_dir / "sample_10k.js")

    # Generate 100k LOC
    generate_fixture(100000, base_dir / "sample_100k.js")

    print("JavaScript fixtures generated successfully!")


if __name__ == "__main__":
    main()
