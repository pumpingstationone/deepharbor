#!/bin/bash
# Start the DHEquipment service
uvicorn main:app --host 0.0.0.0 --port 8000
