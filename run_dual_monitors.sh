#!/bin/bash
# Script to launch both the Palworld and Minecraft Discord monitoring bots concurrently.

# Exit immediately if a command exits with a non-zero status
set -e

echo "--- Starting Dual Discord Bot Monitors ---"

# --- 1. Launch Palworld Monitor ---
echo "Launching Palworld Monitor (palworld_monitor.py) in the background..."
# The 'nohup' command allows the process to run in the background even if the terminal is closed.
# The '&' sends the process to the background immediately.
# Output logs are redirected to palworld_monitor.log
nohup python3 palworld_monitor.py > palworld_monitor.log 2>&1 &
echo "Palworld Monitor started. PID: $!"

# --- 2. Launch Minecraft Monitor ---
echo "Launching Minecraft Monitor (minecraft_monitor.py) in the background..."
# Output logs are redirected to minecraft_monitor.log
nohup python3 minecraft_monitor.py > minecraft_monitor.log 2>&1 &
echo "Minecraft Monitor started. PID: $!"

echo "--- Dual Monitors are running. ---"
echo "Check palworld_monitor.log and minecraft_monitor.log for output and errors."
echo "To check running processes, use: ps aux | grep monitor.py"

# Wait a moment to ensure background processes start cleanly
sleep 1
