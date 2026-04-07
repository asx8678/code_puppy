//! Statistics module — Metrics tracking for turbo_parse operations.
//!
//! Provides thread-safe metrics collection for parse operations including
//! counters, timing, and per-language histograms.

use std::collections::HashMap;
use std::sync::OnceLock;
use parking_lot::RwLock;
use serde::{Deserialize, Serialize};

/// Global singleton metrics instance
static GLOBAL_METRICS: OnceLock<Metrics> = OnceLock::new();

/// Statistics for a specific language
#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct LanguageStats {
    /// Number of parse operations for this language
    pub parse_count: u64,
    /// Total parse time for this language (for calculating average)
    pub total_parse_time_ms: f64,
}

/// Parse operation metrics with thread-safe access
#[derive(Debug)]
pub struct Metrics {
    /// Total number of parse operations across all languages
    total_parses: RwLock<u64>,
    /// Total parse time across all operations (for calculating average)
    total_parse_time_ms: RwLock<f64>,
    /// Per-language statistics
    languages: RwLock<HashMap<String, LanguageStats>>,
}

impl Metrics {
    /// Create a new Metrics instance
    fn new() -> Self {
        Self {
            total_parses: RwLock::new(0),
            total_parse_time_ms: RwLock::new(0.0),
            languages: RwLock::new(HashMap::new()),
        }
    }

    /// Record a parse operation
    ///
    /// # Arguments
    /// * `language` - The language that was parsed
    /// * `parse_time_ms` - Time taken for the parse operation
    pub fn record_parse(&self, language: &str, parse_time_ms: f64) {
        // Update global counters
        {
            let mut total = self.total_parses.write();
            *total += 1;
        }
        {
            let mut total_time = self.total_parse_time_ms.write();
            *total_time += parse_time_ms;
        }

        // Update per-language stats
        let mut langs = self.languages.write();
        let lang_stats = langs.entry(language.to_string()).or_default();
        lang_stats.parse_count += 1;
        lang_stats.total_parse_time_ms += parse_time_ms;
    }

    /// Get the total number of parse operations
    pub fn total_parses(&self) -> u64 {
        *self.total_parses.read()
    }

    /// Get the total parse time across all operations
    pub fn total_parse_time_ms(&self) -> f64 {
        *self.total_parse_time_ms.read()
    }

    /// Calculate the average parse time in milliseconds
    pub fn average_parse_time_ms(&self) -> f64 {
        let total_parses = *self.total_parses.read();
        if total_parses == 0 {
            0.0
        } else {
            *self.total_parse_time_ms.read() / total_parses as f64
        }
    }

    /// Get per-language usage histogram
    pub fn languages_used(&self) -> HashMap<String, LanguageStats> {
        self.languages.read().clone()
    }

    /// Reset all metrics to zero
    #[allow(dead_code)]
    pub fn reset(&self) {
        *self.total_parses.write() = 0;
        *self.total_parse_time_ms.write() = 0.0;
        self.languages.write().clear();
    }
}

impl Default for Metrics {
    fn default() -> Self {
        Self::new()
    }
}

/// Get the global metrics instance
pub fn get_metrics() -> &'static Metrics {
    GLOBAL_METRICS.get_or_init(Metrics::new)
}

/// Record a parse operation in the global metrics
///
/// # Arguments
/// * `language` - The language that was parsed
/// * `parse_time_ms` - Time taken for the parse operation
pub fn record_parse_operation(language: &str, parse_time_ms: f64) {
    get_metrics().record_parse(language, parse_time_ms);
}

/// Statistics snapshot for serialization
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct StatsSnapshot {
    /// Total number of parse operations
    pub total_parses: u64,
    /// Average parse time in milliseconds
    pub average_parse_time_ms: f64,
    /// Per-language usage histogram
    pub languages_used: HashMap<String, LanguageStats>,
}

/// Get current statistics snapshot
pub fn get_stats() -> StatsSnapshot {
    let metrics = get_metrics();
    StatsSnapshot {
        total_parses: metrics.total_parses(),
        average_parse_time_ms: metrics.average_parse_time_ms(),
        languages_used: metrics.languages_used(),
    }
}

/// Get cache statistics combined with parse metrics
///
/// Returns a comprehensive stats object including:
/// - total_parses: count of parse operations
/// - cache_hits/misses from the global cache
/// - average_parse_time_ms
/// - languages_used (histogram)
pub fn get_full_stats() -> serde_json::Value {
    let snapshot = get_stats();
    
    // Get cache stats from global cache if available
    let cache_stats = get_cache_stats();
    
    serde_json::json!({
        "total_parses": snapshot.total_parses,
        "average_parse_time_ms": snapshot.average_parse_time_ms,
        "languages_used": snapshot.languages_used,
        "cache_hits": cache_stats.hits,
        "cache_misses": cache_stats.misses,
        "cache_evictions": cache_stats.evictions,
        "cache_hit_ratio": cache_stats.hit_ratio(),
    })
}

/// Internal cache stats structure
#[derive(Debug, Clone, Copy, Default)]
pub struct CacheStatsInternal {
    pub hits: u64,
    pub misses: u64,
    pub evictions: u64,
}

impl CacheStatsInternal {
    pub fn hit_ratio(&self) -> f64 {
        let total = self.hits + self.misses;
        if total == 0 {
            0.0
        } else {
            self.hits as f64 / total as f64
        }
    }
}

/// Get cache stats from the global cache
fn get_cache_stats() -> CacheStatsInternal {
    // Return default (0 values) if cache not initialized
    if let Some(cache) = crate::GLOBAL_CACHE.get() {
        let stats = cache.stats();
        CacheStatsInternal {
            hits: stats.hits,
            misses: stats.misses,
            evictions: stats.evictions,
        }
    } else {
        CacheStatsInternal::default()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_metrics_new() {
        let metrics = Metrics::new();
        assert_eq!(metrics.total_parses(), 0);
        assert_eq!(metrics.average_parse_time_ms(), 0.0);
    }

    #[test]
    fn test_record_parse() {
        let metrics = Metrics::new();
        metrics.record_parse("python", 10.5);
        
        assert_eq!(metrics.total_parses(), 1);
        assert_eq!(metrics.average_parse_time_ms(), 10.5);
        
        let langs = metrics.languages_used();
        assert_eq!(langs.get("python").unwrap().parse_count, 1);
    }

    #[test]
    fn test_record_multiple_parses() {
        let metrics = Metrics::new();
        metrics.record_parse("python", 10.0);
        metrics.record_parse("python", 20.0);
        metrics.record_parse("rust", 30.0);
        
        assert_eq!(metrics.total_parses(), 3);
        assert_eq!(metrics.average_parse_time_ms(), 20.0);
        
        let langs = metrics.languages_used();
        assert_eq!(langs.get("python").unwrap().parse_count, 2);
        assert_eq!(langs.get("rust").unwrap().parse_count, 1);
    }

    #[test]
    fn test_reset() {
        let metrics = Metrics::new();
        metrics.record_parse("python", 10.0);
        metrics.reset();
        
        assert_eq!(metrics.total_parses(), 0);
        assert_eq!(metrics.average_parse_time_ms(), 0.0);
        assert!(metrics.languages_used().is_empty());
    }

    #[test]
    fn test_get_metrics_singleton() {
        let m1 = get_metrics();
        let m2 = get_metrics();
        // Should be the same instance
        assert!(std::ptr::eq(m1, m2));
    }

    #[test]
    fn test_stats_snapshot() {
        // Note: This tests against the singleton, which may have data from other tests
        // We verify that the stats work correctly, but exact numbers may vary
        let before = get_stats();
        let initial_count = before.total_parses;
        
        // Record a parse operation
        get_metrics().record_parse("test_python", 10.0);
        
        let after = get_stats();
        // Should have incremented by 1
        assert_eq!(after.total_parses, initial_count + 1);
        assert!(after.languages_used.contains_key("test_python"));
    }

    #[test]
    fn test_cache_stats() {
        let stats = get_cache_stats();
        // Initially cache may not be initialized, so defaults to 0
        assert_eq!(stats.hits, 0);
        assert_eq!(stats.misses, 0);
        assert_eq!(stats.evictions, 0);
        assert_eq!(stats.hit_ratio(), 0.0);
    }

    #[test]
    fn test_cache_stats_hit_ratio() {
        let stats = CacheStatsInternal {
            hits: 75,
            misses: 25,
            evictions: 0,
        };
        assert_eq!(stats.hit_ratio(), 0.75);
        
        let empty_stats = CacheStatsInternal::default();
        assert_eq!(empty_stats.hit_ratio(), 0.0);
    }
}
