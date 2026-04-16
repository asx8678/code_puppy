//! Parse Cache - LRU cache for parsed tree-sitter Tree objects.
//!
//! Provides thread-safe caching of parse trees keyed by (file_path, content_hash).
//! Uses parking_lot::RwLock for efficient concurrent access and lru for eviction.

use std::num::NonZeroUsize;
use parking_lot::RwLock;
use lru::LruCache;
use sha2::{Sha256, Digest};
use serde::{Deserialize, Serialize};

/// Default capacity for the parse cache (256 entries)
pub const DEFAULT_CACHE_CAPACITY: usize = 256;

/// Cache key combining file path and content hash
#[derive(Debug, Clone, Hash, Eq, PartialEq, Serialize, Deserialize)]
pub struct CacheKey {
    pub file_path: String,
    pub content_hash: String,
}

impl CacheKey {
    /// Create a new cache key from file path and content
    pub fn new(file_path: impl Into<String>, content: &str) -> Self {
        let file_path = file_path.into();
        let content_hash = compute_content_hash(content);
        Self { file_path, content_hash }
    }

    /// Create a key from pre-computed hash
    pub fn with_hash(file_path: impl Into<String>, content_hash: impl Into<String>) -> Self {
        Self {
            file_path: file_path.into(),
            content_hash: content_hash.into(),
        }
    }
}

/// Cached value containing the parsed tree and metadata
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CacheValue {
    /// Serialized tree representation (placeholder for actual tree-sitter Tree)
    pub tree_data: serde_json::Value,
    /// Language identifier
    pub language: String,
    /// When the entry was cached (Unix timestamp)
    pub cached_at: u64,
}

impl CacheValue {
    /// Create a new cache value
    pub fn new(tree_data: serde_json::Value, language: impl Into<String>) -> Self {
        Self {
            tree_data,
            language: language.into(),
            cached_at: std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap_or_default()
                .as_secs(),
        }
    }
}

/// LRU Cache for parsed tree-sitter Trees
///
/// Thread-safe using parking_lot::RwLock for concurrent reads and exclusive writes.
/// Default capacity is 256 entries, configurable at creation.
pub struct ParseCache {
    inner: RwLock<LruCache<CacheKey, CacheValue>>,
    stats: RwLock<CacheStats>,
}

impl ParseCache {
    /// Create a new ParseCache with default capacity (256 entries)
    pub fn new() -> Self {
        Self::with_capacity(DEFAULT_CACHE_CAPACITY)
    }

    /// Create a new ParseCache with specified capacity
    pub fn with_capacity(capacity: usize) -> Self {
        let cap = NonZeroUsize::new(capacity)
            .unwrap_or_else(|| NonZeroUsize::new(1).expect("1 is guaranteed to be non-zero"));
        Self {
            inner: RwLock::new(LruCache::new(cap)),
            stats: RwLock::new(CacheStats::default()),
        }
    }

    /// Get a value from the cache
    ///
    /// Updates access order for LRU eviction. Updates hit/miss stats.
    pub fn get(&self, key: &CacheKey) -> Option<CacheValue> {
        let mut cache = self.inner.write();
        let mut stats = self.stats.write();

        match cache.get(key) {
            Some(value) => {
                stats.hits += 1;
                Some(value.clone())
            }
            None => {
                stats.misses += 1;
                None
            }
        }
    }

    /// Put a value into the cache
    ///
    /// If the cache is full, the least recently used entry is evicted.
    /// Returns true if an entry was evicted.
    pub fn put(&self, key: CacheKey, value: CacheValue) -> bool {
        let mut cache = self.inner.write();
        let evicted = cache.len() >= cache.cap().get() && !cache.contains(&key);
        cache.put(key, value);
        evicted
    }

    /// Clear all entries from the cache
    pub fn clear(&self) {
        let mut cache = self.inner.write();
        let mut stats = self.stats.write();
        let current_size = cache.len() as u64;
        cache.clear();
        stats.evictions += current_size;
        stats.size = 0;
    }

    /// Get current cache statistics
    pub fn stats(&self) -> CacheStats {
        let cache = self.inner.read();
        let stats = self.stats.read();
        CacheStats {
            size: cache.len(),
            capacity: cache.cap().get(),
            hits: stats.hits,
            misses: stats.misses,
            evictions: stats.evictions,
        }
    }

    /// Get current number of entries in the cache
    pub fn len(&self) -> usize {
        let cache = self.inner.read();
        cache.len()
    }

    /// Check if the cache is empty
    pub fn is_empty(&self) -> bool {
        self.len() == 0
    }

    /// Get the configured capacity
    pub fn capacity(&self) -> usize {
        let cache = self.inner.read();
        cache.cap().get()
    }

    /// Remove a specific entry from the cache
    pub fn remove(&self, key: &CacheKey) -> Option<CacheValue> {
        let mut cache = self.inner.write();
        let mut stats = self.stats.write();
        let removed = cache.pop(key);
        if removed.is_some() {
            stats.size = stats.size.saturating_sub(1);
            stats.evictions += 1;
        }
        removed
    }

    /// Check if a key exists in the cache (without updating LRU order or stats)
    pub fn contains(&self, key: &CacheKey) -> bool {
        let cache = self.inner.read();
        cache.contains(key)
    }
}

impl Default for ParseCache {
    fn default() -> Self {
        Self::new()
    }
}

/// Cache statistics
#[derive(Debug, Clone, Copy, Serialize, Deserialize)]
pub struct CacheStats {
    /// Current number of entries in the cache
    pub size: usize,
    /// Maximum configured capacity
    pub capacity: usize,
    /// Number of cache hits
    pub hits: u64,
    /// Number of cache misses
    pub misses: u64,
    /// Total evictions (including from clear())
    pub evictions: u64,
}

impl CacheStats {
    /// Calculate hit ratio (0.0 to 1.0)
    pub fn hit_ratio(&self) -> f64 {
        let total = self.hits + self.misses;
        if total == 0 {
            0.0
        } else {
            self.hits as f64 / total as f64
        }
    }

    /// Total accesses (hits + misses)
    #[allow(dead_code)]
    pub fn total_accesses(&self) -> u64 {
        self.hits + self.misses
    }
}

impl Default for CacheStats {
    fn default() -> Self {
        Self {
            size: 0,
            capacity: DEFAULT_CACHE_CAPACITY,
            hits: 0,
            misses: 0,
            evictions: 0,
        }
    }
}

/// Compute SHA256 hash of content
pub fn compute_content_hash(content: &str) -> String {
    let mut hasher = Sha256::new();
    hasher.update(content.as_bytes());
    let result = hasher.finalize();
    format!("{:x}", result)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_cache_key_creation() {
        let key = CacheKey::new("test.py", "print('hello')");
        assert_eq!(key.file_path, "test.py");
        assert!(!key.content_hash.is_empty());
    }

    #[test]
    fn test_cache_key_with_hash() {
        let key = CacheKey::with_hash("test.py", "abc123");
        assert_eq!(key.file_path, "test.py");
        assert_eq!(key.content_hash, "abc123");
    }

    #[test]
    fn test_cache_get_put() {
        let cache = ParseCache::new();
        let key = CacheKey::new("test.py", "print('hello')");
        let value = CacheValue::new(serde_json::json!({"root": "test"}), "python");

        // Initially empty
        assert!(cache.get(&key).is_none());
        assert_eq!(cache.stats().misses, 1);

        // Put value
        cache.put(key.clone(), value);
        assert_eq!(cache.len(), 1);

        // Get value back
        let retrieved = cache.get(&key);
        assert!(retrieved.is_some());
        assert_eq!(cache.stats().hits, 1);
    }

    #[test]
    fn test_cache_clear() {
        let cache = ParseCache::new();
        let key = CacheKey::new("test.py", "print('hello')");
        let value = CacheValue::new(serde_json::json!({"root": "test"}), "python");

        cache.put(key, value);
        assert_eq!(cache.len(), 1);

        cache.clear();
        assert_eq!(cache.len(), 0);
    }

    #[test]
    fn test_cache_with_capacity() {
        let cache = ParseCache::with_capacity(2);
        assert_eq!(cache.capacity(), 2);

        let key1 = CacheKey::new("test1.py", "content1");
        let key2 = CacheKey::new("test2.py", "content2");
        let key3 = CacheKey::new("test3.py", "content3");

        let value = CacheValue::new(serde_json::json!({}), "python");

        cache.put(key1.clone(), value.clone());
        cache.put(key2.clone(), value.clone());
        assert_eq!(cache.len(), 2);

        // Adding third entry should evict the least recently used (key1)
        cache.put(key3.clone(), value.clone());
        assert_eq!(cache.len(), 2);
        assert!(cache.get(&key1).is_none()); // Evicted
        assert!(cache.get(&key2).is_some());
        assert!(cache.get(&key3).is_some());
    }

    #[test]
    fn test_cache_stats() {
        let cache = ParseCache::new();
        let key1 = CacheKey::new("test1.py", "content1");
        let key2 = CacheKey::new("test2.py", "content2");
        let value = CacheValue::new(serde_json::json!({}), "python");

        // One hit and one miss
        cache.put(key1.clone(), value.clone());
        assert!(cache.get(&key1).is_some()); // Hit
        assert!(cache.get(&key2).is_none()); // Miss

        let stats = cache.stats();
        assert_eq!(stats.hits, 1);
        assert_eq!(stats.misses, 1);
        assert!(stats.hit_ratio() > 0.49 && stats.hit_ratio() < 0.51);
    }

    #[test]
    fn test_cache_remove() {
        let cache = ParseCache::new();
        let key = CacheKey::new("test.py", "content");
        let value = CacheValue::new(serde_json::json!({}), "python");

        cache.put(key.clone(), value);
        assert_eq!(cache.len(), 1);

        let removed = cache.remove(&key);
        assert!(removed.is_some());
        assert_eq!(cache.len(), 0);

        let not_found = cache.remove(&key);
        assert!(not_found.is_none());
    }

    #[test]
    fn test_cache_contains() {
        let cache = ParseCache::new();
        let key = CacheKey::new("test.py", "content");
        let value = CacheValue::new(serde_json::json!({}), "python");

        assert!(!cache.contains(&key));
        cache.put(key.clone(), value);
        assert!(cache.contains(&key));
    }

    #[test]
    fn test_compute_content_hash() {
        let hash1 = compute_content_hash("hello");
        let hash2 = compute_content_hash("hello");
        let hash3 = compute_content_hash("world");

        assert_eq!(hash1, hash2);
        assert_ne!(hash1, hash3);
        assert_eq!(hash1.len(), 64); // SHA256 hex string length
    }

    #[test]
    fn test_cache_default_capacity() {
        let cache = ParseCache::new();
        assert_eq!(cache.capacity(), DEFAULT_CACHE_CAPACITY);
    }

    #[test]
    fn test_cache_is_empty() {
        let cache = ParseCache::new();
        assert!(cache.is_empty());

        let key = CacheKey::new("test.py", "content");
        let value = CacheValue::new(serde_json::json!({}), "python");
        cache.put(key, value);

        assert!(!cache.is_empty());
    }
}
