#!/bin/bash
# Run this once to keep your Mac awake 24/7 for the trading agent
# Safe to run — just keeps it from sleeping when plugged in

# Prevent sleep on power adapter (lid closed use)
sudo pmset -c sleep 0 disksleep 0

# Disable hibernation (faster wake)
sudo pmset -a hibernatemode 0

# Show current settings
echo "✅ Power settings updated:"
pmset -g | grep -E "sleep|hibernat"

echo ""
echo "Your Mac will now stay awake when plugged in with lid closed."
echo "The Hermes Discord gateway will run 24/7."
echo ""
echo "To undo later: sudo pmset -a sleep 1 disksleep 10"
