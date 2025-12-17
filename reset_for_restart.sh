#!/usr/bin/env bash

# Get the timestamp of when we started this
START_TIME=$(date +"%Y-%m-%d %H:%M:%S")
echo "Resetting Deep Harbor Docker environment. Started at: $START_TIME"

./stop_dh.sh
sleep 2
docker system prune -f -a
./start_dh.sh

# Get the end timestamp
END_TIME=$(date +"%Y-%m-%d %H:%M:%S")
echo "Reset completed. Ended at: $END_TIME"

# Calculate duration
START_SEC=$(date -d "$START_TIME" +%s)
END_SEC=$(date -d "$END_TIME" +%s)
DURATION=$((END_SEC - START_SEC))

# Include minutes and seconds
# Calculate minutes
MINUTES=$((DURATION / 60))
# Calculate seconds
DURATION=$((DURATION % 60))
echo "Total duration: $MINUTES minutes, $DURATION seconds"
