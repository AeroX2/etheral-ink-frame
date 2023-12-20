from typing import Union
from threading import Thread
from pydantic import BaseModel
from fastapi import FastAPI, File, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

import io
import time
import uuid
import tasks
import random
import sqlite3
from pathlib import Path
from datetime import datetime

from PIL import Image

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

@app.get("/prompts")
def prompts(page = 1, limit = 20):
    page = int(page)
    limit = int(limit)
    res = db.execute("SELECT * from prompts ORDER BY date DESC LIMIT ? OFFSET ?", (limit, (page-1)*limit))
    res = [{k : item[k] for k in item.keys()} for item in res]

    count = db.execute("SELECT COUNT(1) from prompts")
    totalSize = count.fetchone()[0]

    return {"status": "ok", "data": res, "totalSize": totalSize}

@app.get("/images")
def images():
    generated_images = [str(x) for x in Path('generated').glob('*')]
    uploaded_images = [str(x) for x in Path('uploaded').glob('*')]

    return {"status": "ok", "generated": generated_images, "uploaded": uploaded_images}

app.paused = False

@app.post("/pause")
def pause():
    app.paused = not app.paused
    return {"status": "ok", "paused": app.paused}
 
@app.post("/cancel")
def cancel():
    app.paused = True
    for worker in tasks.celery.control.inspect().active().values():
        for task in worker:
            print(task)
            if 'generate_image' in task['name']:
                tasks.celery.control.revoke(task['id'], terminate=True)
                return {"status": "ok"}
    return {"status": "error", "error": "Task not found"}

@app.post("/generate")
def generate(prompt: str):
    tasks.generate_image.delay(prompt, f"generated/{uuid.uuid4()}.png")
    return {"status": "ok"}

@app.post("/upload")
def upload(file: UploadFile):
    contents = file.file.read()
    image_name = Path(f'{uuid.uuid4()}.png')
    image_path = str(Path('uploaded') / image_name)
    dithered_image_path = str(Path('dithered') / image_name)

    with Image.open(io.BytesIO(contents)) as img:
        img.thumbnail((800,480), Image.LANCZOS)
        img.save(image_path, "BMP")
    # (tasks.dither_image(image_path, dithered_image_path) | tasks.draw_image(image_path))

    return {"status": "ok"}

class SelectModel(BaseModel):
    image_name: str

@app.post("/select")
def select(model: SelectModel):
    image_name = model.image_name
    image_path = str(Path('dithered') / image_name)
    tasks.draw_image.delay(image_path)
    return {"status": "ok"}

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
        prompts = generate_prompts(3)

        prompts_iter = iter(prompts)
        prompt = next(prompts_iter, None)
        while prompts is not None:
            if app.paused:
                time.sleep(0.5)
                continue

            image_name = Path(f'{uuid.uuid4()}.png')
            image_path = str(Path('generated/') / image_name)
            output_image_path = str(Path('dithered') / image_name)

            (seed,) = tasks.generate_image.delay(prompt, image_path).get()
            save_result(prompt, seed, image_path)
            tasks.dither_image.delay(image_path, output_image_path).get()
            # tasks.draw_image.delay(output_image_path).get()

            prompt = next(prompts_iter, None)
 

@app.on_event("startup")
def startup():
    res = db.execute("SELECT name from sqlite_master where type='table' and name='prompts'").fetchone()
    if res is None:
        db.execute("CREATE TABLE prompts(prompt, seed, image_path, date)")
        db.commit()

    thread = Thread(target=generate_loop)
    thread.start()

Path("generated").mkdir(exist_ok=True)
Path("uploaded").mkdir(exist_ok=True)
Path("dithered").mkdir(exist_ok=True)

app.mount("/generated", StaticFiles(directory="generated"), name="generated")
app.mount("/uploaded", StaticFiles(directory="uploaded"), name="uploaded")
app.mount("/dithered", StaticFiles(directory="dithered"), name="dithered")
app.mount("/", StaticFiles(directory="static", html=True), name="static")

