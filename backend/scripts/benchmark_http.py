"""
Week 7: measures what scripts/benchmark_routes.py can't from inside the
container -- total API latency (HTTP round trip through FastAPI, including
geometry reconstruction and JSON serialization), cold-start vs warm-request
behavior, and process memory. Run on the HOST (not inside a container),
against the already-running docker-compose stack, using the frozen pairs
scripts/benchmark_routes.py already wrote to docs/week7_benchmark_pairs.json.

    python backend/scripts/benchmark_http.py

Requires: requests (already available in this environment), the stack
running via `docker compose up`.
"""
import json
import statistics
import subprocess
import time

import requests

PAIRS_PATH = "docs/week7_benchmark_pairs.json"
OUTPUT_PATH = "docs/week7_benchmark_http.json"
API_BASE = "http://localhost:8000"
WARM_REPEATS = 3


def load_pairs():
    with open(PAIRS_PATH, encoding="utf-8") as f:
        data = json.load(f)
    return data["pairs"]


def time_request(origin, destination):
    body = {
        "origin_lat": origin["lat"], "origin_lon": origin["lon"],
        "destination_lat": destination["lat"], "destination_lon": destination["lon"],
    }
    start = time.perf_counter()
    resp = requests.post(f"{API_BASE}/route/compare", json=body, timeout=30)
    elapsed = time.perf_counter() - start
    return elapsed, resp.status_code, resp.json()


def container_memory_mb(service="new_project-api-1"):
    try:
        out = subprocess.run(
            ["docker", "stats", "--no-stream", "--format", "{{.MemUsage}}", service],
            capture_output=True, text=True, timeout=10, check=True,
        )
        # format like "123.4MiB / 1.9GiB"
        usage = out.stdout.strip().split("/")[0].strip()
        return usage
    except Exception as e:
        return f"unavailable ({e})"


def benchmark_warm(pairs):
    results = []
    for p in pairs:
        if p["status"] != "ok":
            elapsed, status, body = time_request(p["origin"], p["destination"])
            results.append({"category": p["category"], "status_code": status, "response_status": body.get("status"),
                             "elapsed_s_samples": [elapsed]})
            continue

        samples = []
        for _ in range(WARM_REPEATS):
            elapsed, status, body = time_request(p["origin"], p["destination"])
            samples.append(elapsed)
        results.append({
            "category": p["category"],
            "status_code": status,
            "elapsed_s_samples": samples,
            "elapsed_s_median": statistics.median(samples),
            "elapsed_s_min": min(samples),
            "elapsed_s_max": max(samples),
        })
        print(f"{p['category']}: median={statistics.median(samples)*1000:.1f}ms "
              f"min={min(samples)*1000:.1f}ms max={max(samples)*1000:.1f}ms")
    return results


def benchmark_cold_start(pairs):
    """Restarts the api container (fresh graph load) and times the FIRST
    request for the 'long' pair (the slowest, most informative case) vs an
    immediate repeat -- the difference isolates one-time costs (DB
    connection pool warm-up, OS file-cache warm-up, Python bytecode/JIT-ish
    warm-up) from steady-state per-request cost."""
    long_pair = next(p for p in pairs if p["category"] == "long")

    print("Restarting api container for a clean cold-start measurement...")
    subprocess.run(["docker", "compose", "restart", "api"], check=True, timeout=60)

    # Wait for health.
    for _ in range(60):
        try:
            if requests.get(f"{API_BASE}/health/graph", timeout=2).json().get("status") == "ok":
                break
        except Exception:
            pass
        time.sleep(1)
    else:
        raise RuntimeError("api did not become healthy after restart")

    graph_health = requests.get(f"{API_BASE}/health/graph", timeout=5).json()

    cold_elapsed, _, _ = time_request(long_pair["origin"], long_pair["destination"])
    warm_elapsed, _, _ = time_request(long_pair["origin"], long_pair["destination"])

    return {
        "graph_load_seconds": graph_health["load_seconds"],
        "graph_load_rss_mb": graph_health["load_rss_mb"],
        "cold_request_elapsed_s": cold_elapsed,
        "warm_request_elapsed_s": warm_elapsed,
        "memory_after_restart": container_memory_mb(),
    }


def main():
    pairs = load_pairs()

    print("=== Warm-request benchmark (all pairs) ===")
    warm_results = benchmark_warm(pairs)

    print("\n=== Cold-start vs warm benchmark (long pair, fresh container) ===")
    cold_results = benchmark_cold_start(pairs)
    print(json.dumps(cold_results, indent=2))

    memory_steady_state = container_memory_mb()
    print(f"\napi container memory (steady state, after warm benchmark): {memory_steady_state}")

    output = {
        "warm": warm_results,
        "cold_start": cold_results,
        "memory_steady_state": memory_steady_state,
    }
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2)
    print(f"\nWritten to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
