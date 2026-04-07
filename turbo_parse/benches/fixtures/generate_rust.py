#!/usr/bin/env python3
"""Generate Rust test fixtures of various sizes."""

from pathlib import Path


def generate_function(index: int, complexity: str = "medium") -> str:
    """Generate a Rust function with realistic code."""
    if complexity == "simple":
        return f'''/// Simple function {index}
pub fn func_{index}(x: i64) -> i64 {{
    x * {index}
}}

'''
    elif complexity == "medium":
        return f'''/// Process data batch {index}
pub fn process_batch_{index}<T, F>(
    data: Vec<T>,
    transform: F,
) -> Result<Vec<T>, String>
where
    F: Fn(T) -> Result<T, String>,
{{
    let mut results = Vec::with_capacity(data.len());
    for item in data {{
        match transform(item) {{
            Ok(transformed) => results.push(transformed),
            Err(e) => return Err(format!("Transform failed: {{}}", e)),
        }}
    }}
    Ok(results)
}}

'''
    else:  # complex
        return f'''/// Data processor module {index}
pub mod processor_{index} {{
    use std::collections::HashMap;
    use std::sync::{{Arc, Mutex}};

    /// Configuration for processor {index}
    #[derive(Debug, Clone)]
    pub struct Config {{
        pub batch_size: usize,
        pub timeout_ms: u64,
        pub enable_cache: bool,
    }}

    impl Default for Config {{
        fn default() -> Self {{
            Self {{
                batch_size: 100,
                timeout_ms: 5000,
                enable_cache: true,
            }}
        }}
    }}

    /// Processing error types
    #[derive(Debug)]
    pub enum ProcessingError {{
        InvalidInput(String),
        Timeout(u64),
        Internal(String),
    }}

    impl std::fmt::Display for ProcessingError {{
        fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {{
            match self {{
                ProcessingError::InvalidInput(s) => write!(f, "Invalid input: {{}}", s),
                ProcessingError::Timeout(t) => write!(f, "Timeout after {{}}ms", t),
                ProcessingError::Internal(s) => write!(f, "Internal error: {{}}", s),
            }}
        }}
    }}

    impl std::error::Error for ProcessingError {{}}

    /// Processor struct with cache
    pub struct Processor {{
        config: Config,
        cache: Arc<Mutex<HashMap<String, Vec<u8>>>>,
        metrics: Arc<Mutex<Metrics>>,
    }}

    #[derive(Default)]
    struct Metrics {{
        calls: u64,
        cache_hits: u64,
        errors: u64,
    }}

    impl Processor {{
        /// Create new processor with config
        pub fn new(config: Config) -> Self {{
            Self {{
                config,
                cache: Arc::new(Mutex::new(HashMap::new())),
                metrics: Arc::new(Mutex::new(Metrics::default())),
            }}
        }}

        /// Process data with caching
        pub fn process(&self, input: &str) -> Result<Vec<u8>, ProcessingError> {{
            let mut metrics = self.metrics.lock().unwrap();
            metrics.calls += 1;
            drop(metrics);

            if self.config.enable_cache {{
                if let Some(cached) = self.get_cached(input) {{
                    self.metrics.lock().unwrap().cache_hits += 1;
                    return Ok(cached);
                }}
            }}

            let result = self.transform(input)?;
            
            if self.config.enable_cache {{
                self.cache_result(input, &result);
            }}

            Ok(result)
        }}

        fn get_cached(&self, key: &str) -> Option<Vec<u8>> {{
            self.cache.lock().unwrap().get(key).cloned()
        }}

        fn cache_result(&self, key: &str, value: &[u8]) {{
            self.cache.lock().unwrap().insert(key.to_string(), value.to_vec());
        }}

        fn transform(&self, input: &str) -> Result<Vec<u8>, ProcessingError> {{
            if input.is_empty() {{
                return Err(ProcessingError::InvalidInput("Empty input".to_string()));
            }}
            Ok(input.bytes().map(|b| b.wrapping_add(1)).collect())
        }}
    }}
}}

'''


def generate_imports() -> str:
    """Generate realistic Rust imports and crate prelude."""
    return '''//! Large Rust module for benchmark testing
#![allow(dead_code, unused_imports)]

use std::collections::{{HashMap, HashSet, BTreeMap, VecDeque}};
use std::fmt::{{self, Debug, Display}};
use std::io::{{self, Read, Write, BufRead, BufReader}};
use std::sync::{{Arc, Mutex, RwLock, atomic::{{AtomicU64, Ordering}}}};
use std::time::{{Duration, Instant}};

use serde::{{Deserialize, Serialize}};
use tokio::{{sync::{{mpsc, oneshot}}, task, time::timeout}};
use anyhow::{{Result, Context, bail}};
use thiserror::Error;

/// Module version constant
pub const VERSION: &str = env!("CARGO_PKG_VERSION");

/// Maximum batch size
pub const MAX_BATCH_SIZE: usize = 10_000;

/// Default timeout in milliseconds
pub const DEFAULT_TIMEOUT_MS: u64 = 30_000;

'''


def generate_fixture(target_lines: int, output_path: Path) -> int:
    """Generate a Rust file with approximately target_lines lines of code."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    lines_written = 0
    functions_written = 0
    
    with open(output_path, "w") as f:
        # Write imports (approx 20 lines)
        imports = generate_imports()
        f.write(imports)
        lines_written += len(imports.split("\n"))
        
        # Mix of function complexities
        while lines_written < target_lines:
            # Vary complexity based on progress
            if functions_written < target_lines // 40:
                complexity = "simple"
            elif functions_written < target_lines // 15:
                complexity = "medium"
            else:
                complexity = "complex"
            
            func_code = generate_function(functions_written, complexity)
            f.write(func_code)
            lines_written += len(func_code.split("\n"))
            functions_written += 1
            
            # Add occasional modules and traits
            if functions_written % 25 == 0:
                trait_code = f'''/// Trait definition set {{functions_written // 25}}
pub trait ProcessorTrait{functions_written // 25} {{
    type Input;
    type Output;
    type Error: std::error::Error;
    
    fn process(&self, input: Self::Input) -> Result<Self::Output, Self::Error>;
    fn validate(&self, input: &Self::Input) -> bool;
}}

/// Blanket implementation for reference types
impl<T: ProcessorTrait{functions_written // 25}> ProcessorTrait{functions_written // 25} for &T {{
    type Input = T::Input;
    type Output = T::Output;
    type Error = T::Error;
    
    fn process(&self, input: Self::Input) -> Result<Self::Output, Self::Error> {{
        (*self).process(input)
    }}
    
    fn validate(&self, input: &Self::Input) -> bool {{
        (*self).validate(input)
    }}
}}

'''
                f.write(trait_code)
                lines_written += len(trait_code.split("\n"))
    
    # Count actual lines
    with open(output_path) as f:
        actual_lines = len(f.readlines())
    
    print(f"Generated {output_path}: {actual_lines} lines (target: {target_lines})")
    return actual_lines


def main():
    """Generate all Rust fixtures."""
    base_dir = Path(__file__).parent / "rust"
    
    # Generate 1k LOC
    generate_fixture(1000, base_dir / "sample_1k.rs")
    
    # Generate 10k LOC
    generate_fixture(10000, base_dir / "sample_10k.rs")
    
    # Generate 100k LOC
    generate_fixture(100000, base_dir / "sample_100k.rs")
    
    print("Rust fixtures generated successfully!")


if __name__ == "__main__":
    main()
