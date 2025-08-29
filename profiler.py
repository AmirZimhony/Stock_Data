import cProfile
import pstats
import main
import psutil
import subprocess
import argparse

parser = argparse.ArgumentParser()
parser.add_argument("--env", help="Environment to run the script in")
args = parser.parse_args()

def run_cmd():
    subprocess.run(["python", "main.py", "--env", args.env])   # replace with your command

cProfile.run("run_cmd()", "profile_output.prof")
# cProfile.run('main.main()', filename='profile_output.prof')
p = pstats.Stats('profile_output.prof')
p.strip_dirs().sort_stats('cumulative').print_stats(10)

# CPU usage
print("CPU Usage:", psutil.cpu_percent())

# Memory usage
memory = psutil.virtual_memory()
print("Memory Usage (in bytes):", memory.used)