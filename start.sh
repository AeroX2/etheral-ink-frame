#!/bin/sh

redis-server &
celery -A tasks.celery worker &
celery -A tasks.celery flower &

uvicorn server:app --reload --host 0.0.0.0

sleep 5

python start.py
