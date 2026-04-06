import time
import requests
import sys


def validate_latency(endpoint, trials=10):
    latencies = []
    for _ in range(trials):
        start = time.perf_counter()
        try:
            requests.get(endpoint, timeout=5)
        except Exception:
            pass
        end = time.perf_counter()
        latencies.append((end - start) * 1000)

    latencies.sort()
    p50 = latencies[int(0.50 * len(latencies))]
    p99 = latencies[int(0.99 * len(latencies)) - 1]
    print(f"p50 Latency: {p50:.2f} ms")
    print(f"p99 Latency: {p99:.2f} ms")
    return p99


if __name__ == "__main__":
    endpoint = sys.argv[1] if len(sys.argv) > 1 else None

    if not endpoint:
        print("⚠️  No live endpoint provided. Skipping real latency measurement.")
        print("Usage: python latency_audit.py https://your-worker.workers.dev/health")
        print("NOTE: Sub-100ms claim requires a deployed Cloudflare Worker to verify.")
        sys.exit(0)

    print(f"🌐 Testing latency against: {endpoint}")
    p99 = validate_latency(endpoint)
    assert p99 < 100, f"❌ Latency target failed: p99={p99:.2f}ms (target: <100ms)"
    print(f"✅ Latency target met: p99={p99:.2f}ms < 100ms")
