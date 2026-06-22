#!/bin/bash

# Reset ADB to prevent protocol faults
echo "🔄 Resetting ADB server..."
adb kill-server
adb start-server

# Get IP and Port from user
echo "------------------------------------------------"
echo "📱 Look at your phone under 'Endereço IP e porta'"
echo "------------------------------------------------"
read -p "Enter the PORT number only (the numbers after the :): " port

# Connect using your phone's current IP
# (Hardcoded to your IP 192.168.1.27 based on your previous logs)
echo "🔌 Connecting to 192.168.1.27:$port..."
adb connect 192.168.1.27:$port

# Show status
echo "------------------------------------------------"
adb devices