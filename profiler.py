import cProfile
import pstats
import main
import psutil


cProfile.run('main.main()', filename='profile_output.prof')
p = pstats.Stats('profile_output.prof')
p.strip_dirs().sort_stats('cumulative').print_stats(10)

# CPU usage
print("CPU Usage:", psutil.cpu_percent())

# Memory usage
memory = psutil.virtual_memory()
print("Memory Usage (in bytes):", memory.used)