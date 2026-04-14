// ═══════════════════════════════════════════════════════════════════════════════
// Parse Cache - LRU Cache for Parsed Trees
// ═══════════════════════════════════════════════════════════════════════════════
//
// Migration from: turbo_parse/src/cache.rs
//
// Caches parse results keyed by content hash. This enables:
//   - Fast re-parsing of unchanged files
//   - Memory pressure management via LRU eviction
//   - Thread-safe concurrent access
//
// Zig vs Rust differences:
//   - std.HashMap instead of DashMap (no concurrent hash map in std yet)
//   - Explicit synchronization vs DashMap's internal locking

const std = @import("std");
const c_api = @import("c_api.zig");

// ═══════════════════════════════════════════════════════════════════════════════
// Cache Key
// ═══════════════════════════════════════════════════════════════════════════════

pub const CacheKey = struct {
    content_hash: u64,
    language: []const u8,
    
    pub fn hash(self: @This()) u64 {
        var hasher = std.hash.Wyhash.init(0);
        hasher.update(&std.mem.toBytes(self.content_hash));
        hasher.update(self.language);
        return hasher.final();
    }
    
    pub fn eql(self: @This(), other: @This()) bool {
        return self.content_hash == other.content_hash and 
               std.mem.eql(u8, self.language, other.language);
    }
};

pub const CacheKeyContext = struct {
    pub fn hash(_: @This(), key: CacheKey) u64 {
        return key.hash();
    }
    
    pub fn eql(_: @This(), a: CacheKey, b: CacheKey) bool {
        return a.eql(b);
    }
};

// ═══════════════════════════════════════════════════════════════════════════════
// Cache Value
// ═══════════════════════════════════════════════════════════════════════════════

pub const CacheValue = struct {
    tree: *c_api.TSTree,  // Owned, must be deleted
    language: []const u8,  // Owned copy
    timestamp: i64,
    access_count: u64,
    
    pub fn deinit(self: *CacheValue, allocator: std.mem.Allocator) void {
        c_api.ts_tree_delete(self.tree);
        allocator.free(self.language);
    }
};

// ═══════════════════════════════════════════════════════════════════════════════
// LRU Node (for eviction tracking)
// ═══════════════════════════════════════════════════════════════════════════════

const LRUNode = struct {
    key: CacheKey,
    next: ?*LRUNode,
    prev: ?*LRUNode,
};

// ═══════════════════════════════════════════════════════════════════════════════
// ParseCache
// ═══════════════════════════════════════════════════════════════════════════════

pub const DEFAULT_CACHE_CAPACITY: usize = 1000;

pub const ParseCache = struct {
    allocator: std.mem.Allocator,
    entries: std.HashMap(CacheKey, CacheValue, CacheKeyContext, std.hash_map.default_max_load_percentage),
    capacity: usize,
    lock: std.Thread.Mutex,
    
    // Statistics
    hits: u64,
    misses: u64,
    evictions: u64,
    
    const Self = @This();
    
    pub fn init(allocator: std.mem.Allocator, capacity: usize) Self {
        return .{
            .allocator = allocator,
            .entries = std.HashMap(CacheKey, CacheValue, CacheKeyContext, std.hash_map.default_max_load_percentage).init(allocator),
            .capacity = capacity,
            .lock = .{},
            .hits = 0,
            .misses = 0,
            .evictions = 0,
        };
    }
    
    pub fn deinit(self: *Self) void {
        var iter = self.entries.valueIterator();
        while (iter.next()) |value| {
            var v = value.*;
            v.deinit(self.allocator);
        }
        
        // Free all owned keys
        var key_iter = self.entries.keyIterator();
        while (key_iter.next()) |key| {
            self.allocator.free(key.language);
        }
        
        self.entries.deinit();
    }
    
    /// Look up a cached parse tree
    pub fn get(self: *Self, key: CacheKey) ?CacheValue {
        self.lock.lock();
        defer self.lock.unlock();
        
        if (self.entries.getPtr(key)) |entry| {
            entry.timestamp = std.time.milliTimestamp();
            entry.access_count += 1;
            self.hits += 1;
            
            // Return a copy (caller owns the tree copy)
            return CacheValue{
                .tree = c_api.ts_tree_copy(entry.tree),
                .language = try self.allocator.dupe(u8, entry.language),
                .timestamp = entry.timestamp,
                .access_count = entry.access_count,
            };
        }
        
        self.misses += 1;
        return null;
    }
    
    /// Insert a parsed tree into cache
    pub fn put(
        self: *Self,
        key: CacheKey,
        tree: *c_api.TSTree,
        language: []const u8,
    ) error{ OutOfMemory, CacheFull }!void {
        self.lock.lock();
        defer self.lock.unlock();
        
        // Evict if at capacity
        if (self.entries.count() >= self.capacity) {
            try self.evictLRU();
        }
        
        // Deep copy key
        const owned_key = CacheKey{
            .content_hash = key.content_hash,
            .language = try self.allocator.dupe(u8, language),
        };
        
        const value = CacheValue{
            .tree = tree,  // We take ownership
            .language = try self.allocator.dupe(u8, language),
            .timestamp = std.time.milliTimestamp(),
            .access_count = 1,
        };
        
        // Remove old entry if exists
        if (self.entries.fetchRemove(owned_key)) |old| {
            var v = old.value;
            v.deinit(self.allocator);
            self.allocator.free(old.key.language);
        }
        
        try self.entries.put(owned_key, value);
    }
    
    /// Compute content hash using xxHash64 (fallback to Wyhash)
    pub fn computeContentHash(content: []const u8) u64 {
        return std.hash.Wyhash.hash(0, content);
    }
    
    /// Clear all cached entries
    pub fn clear(self: *Self) void {
        self.lock.lock();
        defer self.lock.unlock();
        
        var iter = self.entries.iterator();
        while (iter.next()) |entry| {
            entry.value_ptr.deinit(self.allocator);
            self.allocator.free(entry.key_ptr.language);
        }
        
        self.entries.clearRetainingCapacity();
    }
    
    /// Get cache statistics
    pub fn stats(self: *Self) CacheStats {
        self.lock.lock();
        defer self.lock.unlock();
        
        return CacheStats{
            .hits = self.hits,
            .misses = self.misses,
            .evictions = self.evictions,
            .entries = self.entries.count(),
            .capacity = self.capacity,
        };
    }
    
    fn evictLRU(self: *Self) error{CacheFull}!void {
        // Simple eviction: remove first entry (deterministic but not truly LRU)
        // TODO(code-puppy-zig-019): Implement proper LRU with linked list
        
        var iter = self.entries.iterator();
        if (iter.next()) |entry| {
            const key_to_remove = entry.key_ptr.*;
            
            entry.value_ptr.deinit(self.allocator);
            self.allocator.free(entry.key_ptr.language);
            
            _ = self.entries.remove(key_to_remove);
            self.evictions += 1;
        } else {
            return error.CacheFull;
        }
    }
};

pub const CacheStats = struct {
    hits: u64,
    misses: u64,
    evictions: u64,
    entries: usize,
    capacity: usize,
    
    pub fn hitRate(self: @This()) f64 {
        const total = self.hits + self.misses;
        if (total == 0) return 0.0;
        return @as(f64, @floatFromInt(self.hits)) / @as(f64, @floatFromInt(total));
    }
};

// ═══════════════════════════════════════════════════════════════════════════════
// Tests
// ═══════════════════════════════════════════════════════════════════════════════

test "cache basic operations" {
    const allocator = std.testing.allocator;
    
    var cache = ParseCache.init(allocator, 10);
    defer cache.deinit();
    
    _ = CacheKey{
        .content_hash = 12345,
        .language = "python",
    };

    // Note: Can't test put/get without a real TSTree
    // This test verifies initialization works

    const stats = cache.stats();
    try std.testing.expectEqual(@as(usize, 0), stats.entries);
    try std.testing.expectEqual(@as(usize, 10), stats.capacity);
}

test "content hash" {
    const hash1 = ParseCache.computeContentHash("hello world");
    const hash2 = ParseCache.computeContentHash("hello world");
    const hash3 = ParseCache.computeContentHash("different content");
    
    try std.testing.expectEqual(hash1, hash2);
    try std.testing.expect(hash1 != hash3);
}
