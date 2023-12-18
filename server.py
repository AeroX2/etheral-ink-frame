from typing import Union
from threading import Thread
from fastapi import FastAPI, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

import time
import uuid
import tasks
import random
import sqlite3
from datetime import datetime

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

db = sqlite3.connect('database.db', check_same_thread=False)
db.row_factory = sqlite3.Row

#@app.get("/")
#def root():
#    return {"Hello": "World"}

@app.get("/generate")
def generate(prompt: str):
    tasks.generate_image.delay(prompt, f"generated/{uuid.uuid4()}.png")
    return {"status": "ok"}
 
@app.get("/cancel")
def cancel():
    for worker in tasks.celery.control.inspect().active().values():
        for task in worker:
            print(task)
            if 'generate_image' in task['name']:
                tasks.celery.control.revoke(task['id'], terminate=True)
                return {"status": "ok"}
    return {"status": "error", "error": "Task not found"}

app.paused = False

@app.get("/pause")
def pause():
    app.paused = not app.paused
    return {"status": "ok", "paused": app.paused}

@app.get("/prompts")
def prompts(page = 0, limit = 20):
    page = int(page)
    limit = int(limit)
    res = db.execute("SELECT * from prompts ORDER BY date DESC LIMIT ? OFFSET ?", (limit, page*limit))
    res = [{k : item[k] for k in item.keys()} for item in res]

    count = db.execute("SELECT COUNT(1) from prompts")

    return {"status": "ok", "data": res, "totalSize": count.fetchone()[0]}

# Scheduling section

def generate_prompts(amount: int):
    with open('data/prompt_data.txt') as f:
        line = [x.strip() for x in f.readlines()]
        prompts = [", ".join([random.choice(line) for ii in range(random.randint(3,8))]) for i in range(amount)]

    for prompt in prompts:
        db.execute("INSERT INTO prompts VALUES(?, NULL, NULL, NULL)", (prompt,))
    db.commit()
    return prompts

def save_result(prompt, seed, image_path):
    db.execute("UPDATE prompts SET seed=?, image_path=?, date=? WHERE prompt=?", (seed, image_path, datetime.now(), prompt))
    db.commit()

def generate_loop():
    # Wait for Celery, Redis and stuff to boot
    time.sleep(3)

    while True:
        prompts = generate_prompts(20)

        prompts_iter = iter(prompts)
        prompt = next(prompts_iter)
        while prompts is not None:
            if app.paused:
                time.sleep(0.5)
                continue
            image_path = f'generated/{uuid.uuid4()}.png'
            (seed,) = tasks.generate_image.delay(prompt, image_path).get()
            save_result(prompt, seed, image_path)

            prompt = next(prompts_iter)
 

@app.on_event("startup")
def startup():
    res = db.execute("SELECT name from sqlite_master where type='table' and name='prompts'").fetchone()
    print(res)
    if res is None:
        db.execute("CREATE TABLE prompts(prompt, seed, image_path, date)")
        db.commit()

    thread = Thread(target=generate_loop)
    thread.start()

app.mount("/", StaticFiles(directory="static", html=True), name="static")
