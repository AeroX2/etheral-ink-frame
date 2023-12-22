#!/bin/sh

redis-server &
#watchmedo auto-restart --directory=./ --pattern=tasks.py --recursive -- celery -A tasks.celery worker & > celery-worker.log
python3 -m celery -A tasks.celery worker -f celery-worker.log &
python3 -m celery -A tasks.celery flower -f celery-flower.log &

python3 -m uvicorn server:app --host 0.0.0.0 &
