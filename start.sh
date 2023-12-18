#!/bin/sh

redis-server & > redis.log
watchmedo auto-restart --directory=./ --pattern=tasks.py --recursive -- celery -A tasks.celery worker & > celery-worker.log
celery -A tasks.celery flower & > celery-flower.log

uvicorn server:app --reload --host 0.0.0.0 &
