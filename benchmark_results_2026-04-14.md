# Benchmark Results - April 14, 2026

## Python vs Elixir Control Plane Comparison

### Full Python Benchmark Output

```
============================================================
ELIXIR CONTROL PLANE vs PYTHON-ONLY BENCHMARK SUITE
============================================================

Mode: QUICK
Benchmarks: throughput, concurrent, fault, latency, spawn
Worker Script: /Users/adam2/projects/code_puppy/scripts/bench_worker.py

============================================================
BENCHMARK 1: Spawn Latency
============================================================

Running Elixir Control Plane (JSON-RPC over pipes)...
  mean=19.949ms, median=20.243ms, p95=21.235ms, p99=21.235ms, stdev=1.051ms (n=20)

Running Python-Only (direct subprocess)...
  mean=11.520ms, median=11.384ms, p95=12.886ms, p99=12.886ms, stdev=0.591ms (n=20)

----------------------------------------
  Elixir Control Plane is 1.73x slower than Python-Only

============================================================
BENCHMARK 2: Request/Response Latency
============================================================

Running Elixir Control Plane (JSON-RPC round-trip)...
  mean=0.036ms, median=0.032ms, p95=0.058ms, p99=0.058ms, stdev=0.012ms (n=20)

Running Python-Only (direct function call)...
  mean=0.000ms, median=0.000ms, p95=0.001ms, p99=0.001ms, stdev=0.000ms (n=20)

----------------------------------------
  Elixir Control Plane is 207.66x slower than Python-Only

============================================================
BENCHMARK 3: Throughput Under Load
============================================================

Running Elixir Control Plane...
  Total ops: 100
  Total time: 2.24ms
  Throughput: 44695.23 ops/sec
  Per-op latency:
    mean=0.022ms, median=0.021ms, p95=0.026ms, p99=0.042ms, stdev=0.004ms (n=100)

Running Python-Only...
  Total ops: 100
  Total time: 0.02ms
  Throughput: 4743157.99 ops/sec
  Per-op latency:
    mean=0.000ms, median=0.000ms, p95=0.000ms, p99=0.000ms, stdev=0.000ms (n=100)

----------------------------------------
  Elixir Control Plane is 106.12x slower than Python-Only

============================================================
BENCHMARK 4: Concurrent Workers
============================================================

Running Elixir Control Plane...

  Workers: 1
    Total ops: 25
    Throughput: 23623.91 ops/sec
    Per-op latency:
      mean=0.027ms, median=0.023ms, p95=0.029ms, p99=0.042ms, stdev=0.016ms (n=25)

  Workers: 4
    Total ops: 100
    Throughput: 55505.45 ops/sec
    Per-op latency:
      mean=0.045ms, median=0.038ms, p95=0.074ms, p99=0.186ms, stdev=0.027ms (n=100)

  Workers: 8
    Total ops: 200
    Throughput: 57827.84 ops/sec
    Per-op latency:
      mean=0.096ms, median=0.096ms, p95=0.156ms, p99=0.181ms, stdev=0.039ms (n=200)

Running Python-Only...

  Workers: 1
    Total ops: 25
    Throughput: 40529.61 ops/sec
    Per-op latency:
      mean=0.000ms, median=0.000ms, p95=0.000ms, p99=0.001ms, stdev=0.001ms (n=25)

  Workers: 4
    Total ops: 100
    Throughput: 211286.06 ops/sec
    Per-op latency:
      mean=0.000ms, median=0.000ms, p95=0.000ms, p99=0.001ms, stdev=0.000ms (n=100)

  Workers: 8
    Total ops: 200
    Throughput: 537153.57 ops/sec
    Per-op latency:
      mean=0.000ms, median=0.000ms, p95=0.000ms, p99=0.001ms, stdev=0.000ms (n=200)

============================================================
BENCHMARK 5: Fault Recovery
============================================================

Running Elixir Control Plane...
  Detection time: 14.032ms
  Respawn time: 18.821ms
  Total recovery: 32.853ms

Running Python-Only...
  Detection time: 1.331ms
  Respawn time: 11.268ms
  Total recovery: 12.600ms

----------------------------------------
  Elixir Control Plane is 2.61x slower for fault recovery

============================================================
BENCHMARK COMPLETE
============================================================
```

---

### Full Elixir Benchmark Output (JSON)

```json
{
  "metadata": {
    "timestamp": "2026-04-14T08:24:25.223398Z",
    "mode": "quick",
    "elixir_version": "1.19.5",
    "otp_version": "28"
  },
  "spawn_latency": {
    "iterations": 3,
    "mean_us": 18812.67,
    "median_us": 15865,
    "p95_us": 24350.20,
    "min_us": 15280,
    "max_us": 25293
  },
  "echo_latency": {
    "iterations": 20,
    "mean_us": 25.1,
    "median_us": 23.0,
    "p95_us": 35.45,
    "min_us": 17,
    "max_us": 44,
    "errors": 0
  },
  "concurrent_scaling": [
    {
      "num_workers": 1,
      "requests_per_worker": 5,
      "mean_us": 76.4,
      "median_us": 83,
      "p95_us": 92.4,
      "throughput_rps": 351.40
    },
    {
      "num_workers": 2,
      "requests_per_worker": 5,
      "mean_us": 92.0,
      "median_us": 90.0,
      "p95_us": 117.55,
      "throughput_rps": 673.49
    },
    {
      "num_workers": 4,
      "requests_per_worker": 5,
      "mean_us": 210.45,
      "median_us": 211.5,
      "p95_us": 248.45,
      "throughput_rps": 1079.21
    }
  ],
  "fault_recovery": {
    "detection_time_us": 10986,
    "initial_count": 1,
    "final_count": 0,
    "worker_gone": true
  }
}
```

---

## Summary Comparison Table

| Benchmark | Python-Only | Elixir Control Plane | Difference |
|-----------|-------------|---------------------|------------|
| **Spawn Latency (mean)** | 11.52 ms | 19.95 ms | Elixir ~1.7x slower |
| **Req/Resp Latency (mean)** | ~0 ms (direct) | 0.036 ms (JSON-RPC) | Elixir ~208x slower* |
| **Throughput (1 worker)** | 40,530 ops/s | 23,624 ops/s | Python ~1.7x faster |
| **Throughput (4 workers)** | 211,286 ops/s | 55,505 ops/s | Python ~3.8x faster |
| **Throughput (8 workers)** | 537,154 ops/s | 57,828 ops/s | Python ~9.3x faster |
| **Fault Recovery** | 12.60 ms total | 32.85 ms total | Python ~2.6x faster |

\* Note: Python direct function calls are nearly instantaneous compared to JSON-RPC round-trip overhead.

### Key Observations

1. **Direct Python is faster for raw speed** - No surprise here. Direct function calls will always beat JSON-RPC over pipes.

2. **Elixir scales with workers** - Throughput increases from 351 RPS (1 worker) → 673 RPS (2 workers) → 1079 RPS (4 workers), showing good scaling characteristics.

3. **Elixir overhead is consistent** - The ~18-25 μs JSON-RPC latency is predictable and small enough for most use cases.

4. **Fault recovery trade-off** - Elixir's distributed supervision adds ~20ms overhead but provides stronger guarantees.

### Conclusion

Choose **Python-only** for: Maximum throughput, minimal latency, simple deployments.

Choose **Elixir Control Plane** for: Fault tolerance, distributed orchestration, supervision trees, production resilience.
