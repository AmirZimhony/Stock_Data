import argparse
import cProfile
import logging
import os
import pstats
import sys
import time
import tracemalloc

import psutil

# Configure logging for profiler
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def get_memory_usage():
    """Get detailed memory usage information"""
    process = psutil.Process(os.getpid())
    memory_info = process.memory_info()
    return {
        "rss": memory_info.rss,  # Physical memory
        "vms": memory_info.vms,  # Virtual memory
        "percent": process.memory_percent(),
        "available": psutil.virtual_memory().available,
    }


def analyze_cpu_consumers(stats_obj, top_n=15):
    """Analyze and display top CPU consuming functions"""
    logger.info(f"\n=== TOP {top_n} CPU CONSUMERS (by cumulative time) ===")
    stats_obj.strip_dirs().sort_stats("cumulative").print_stats(top_n)

    logger.info(f"\n=== TOP {top_n} CPU CONSUMERS (by total time) ===")
    stats_obj.strip_dirs().sort_stats("tottime").print_stats(top_n)


def analyze_memory_consumers():
    """Analyze memory usage patterns"""
    logger.info("\n=== MEMORY ANALYSIS ===")

    # Get current memory snapshot
    if tracemalloc.is_tracing():
        current, peak = tracemalloc.get_traced_memory()
        logger.info(
            f"Traced Memory - Current: {current / 1024 / 1024:.2f} MB, Peak: {peak / 1024 / 1024:.2f} MB"
        )

        # Get top memory consumers
        snapshot = tracemalloc.take_snapshot()
        top_stats = snapshot.statistics("lineno")

        logger.info("\n=== TOP 10 MEMORY CONSUMERS (by line) ===")
        for index, stat in enumerate(top_stats[:10], 1):
            logger.info(
                f"{index}. {stat.traceback.format()[-1]} - {stat.size / 1024 / 1024:.2f} MB ({stat.count} blocks)"
            )


parser = argparse.ArgumentParser()
parser.add_argument(
    "--top", type=int, default=15, help="Number of top consumers to show"
)
args = parser.parse_args()

# main.py with no --env loads dev.json (same as normal local dev)
sys.argv = ["main.py"]

# Start memory tracing
tracemalloc.start()

# Get initial memory usage
initial_memory = get_memory_usage()
logger.info(
    f"Initial Memory Usage: {initial_memory['rss'] / 1024 / 1024:.2f} MB RSS, {initial_memory['vms'] / 1024 / 1024:.2f} MB VMS"
)

# Import main after setting sys.argv (needed by the cProfile.run() string below)
import main  # noqa: E402,F401

logger.info("Profiling main.py (dev.json / default dev)")

# Profile the actual main function
profile_filename = "profile_output_dev.prof"
start_time = time.time()
cProfile.run("main.main()", filename=profile_filename)
end_time = time.time()

# Get final memory usage
final_memory = get_memory_usage()
memory_diff = final_memory["rss"] - initial_memory["rss"]

# Analyze results
p = pstats.Stats(profile_filename)

# Show CPU consumers
analyze_cpu_consumers(p, args.top)

# Show memory consumers
analyze_memory_consumers()

# System metrics summary
logger.info("\n=== PERFORMANCE SUMMARY ===")
logger.info(f"Total Execution Time: {end_time - start_time:.2f} seconds")
logger.info(f"Memory Usage Change: {memory_diff / 1024 / 1024:+.2f} MB")
logger.info(
    f"Final Memory Usage: {final_memory['rss'] / 1024 / 1024:.2f} MB RSS ({final_memory['percent']:.1f}%)"
)
logger.info(f"Peak Memory: {final_memory['vms'] / 1024 / 1024:.2f} MB VMS")
logger.info(f"CPU Usage: {psutil.cpu_percent(interval=1)}%")
logger.info(
    f"Available Memory: {final_memory['available'] / 1024 / 1024 / 1024:.2f} GB"
)


p = psutil.Process(os.getpid())
rss_mb = p.memory_info().rss / 1024 / 1024
uss_mb = (
    getattr(p.memory_full_info(), "uss", p.memory_info().rss) / 1024 / 1024
)  # unique set size
print(f"RSS: {rss_mb:.1f} MB, USS: {uss_mb:.1f} MB")
# Stop memory tracing
tracemalloc.stop()
