from threading import Thread
from pydantic import BaseModel
from fastapi import FastAPI, BackgroundTasks, File, UploadFile, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

import os
import io
import sys
import time
import uuid
import tasks
import random
import sqlite3
from pathlib import Path
from datetime import datetime

from PIL import Image, ImageOps

libdir = os.path.join(os.path.dirname(os.path.dirname(os.path.realpath(__file__))), 'lib')
if os.path.exists(libdir):
    sys.path.append(libdir)
from waveshare_epd import epdconfig, epd7in3f
import importlib

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

    #TODO (jridey) Probably a much betteer way of doing this
    os.system("killall sd")

    try:
        for worker in tasks.celery.control.inspect().active().values():
            for task in worker:
                if 'generate_image' in task['name']:
                    tasks.celery.control.revoke(task['id'], terminate=True)
                return {"status": "ok"}
    except Exception as e:
        return {"status": "error", "error": str(e)}
    return {"status": "error", "error": "Task not found"}

class GenerateModel(BaseModel):
    prompt: str

@app.post("/generate")
def generate(model: GenerateModel):
    tasks.generate_image.delay(model.prompt, f"generated/{uuid.uuid4()}.png")
    return {"status": "ok"}

@app.post("/upload")
def upload(file: UploadFile = File(...)):
    contents = file.file.read()
    image_name = Path(f'{uuid.uuid4()}.png')
    image_path = str(Path('uploaded') / image_name)

    with Image.open(io.BytesIO(contents)) as img:
        img = ImageOps.contain(img, (800,480))
        img = ImageOps.pad(img, (800,480), color='#fff')
        img.save(image_path, "PNG")
    draw_image(image_path)

    return {"status": "ok"}

class SelectModel(BaseModel):
    image_path: str

@app.post("/select")
def select(model: SelectModel, background_tasks: BackgroundTasks):
    background_tasks.add_task(draw_image, model.image_path)
    return {"status": "ok"}

# Scheduling section

def generate_prompts(amount: int):
    with open('data/prompt_data.txt') as f:
        lines = [x.strip() for x in f.readlines() if x.strip() != '']
        prompts = [" ".join(random.sample(lines, random.randint(1,5))) for i in range(amount)]

    with open('data/attribute_data.txt') as f:
        lines = [x.strip() for x in f.readlines() if x.strip() != '']
        attrs = [", ".join(random.sample(lines, random.randint(1,3))) for i in range(amount)]
        prompts = [f"{prompt}, {attr}" for prompt, attr in zip(prompts, attrs)]

    for prompt in prompts:
        db.execute("INSERT INTO prompts VALUES(?, NULL, NULL, NULL)", (prompt,))
    db.commit()
    return prompts

def save_result(prompt, seed, image_path):
    db.execute("UPDATE prompts SET seed=?, image_path=?, date=? WHERE prompt=?", (seed, image_path, datetime.now(), prompt))
    db.commit()

app.display_initialized = False
def draw_image(file_path: str):
    if not os.path.exists(file_path):
        print("File doesn't exist for drawing")
        return
    
    try:
        if (app.display_initialized):
            importlib.reload(epdconfig)
        app.display_initialized = True
        epd = epd7in3f.EPD()
        epd.init()

        with Image.open(file_path) as img:
            img = ImageOps.contain(img, (800,480))
            img = ImageOps.pad(img, (800,480), color='#fff')
            epd.display(epd.getbuffer(img))

        epd.sleep()
        
    except Exception as e:
        print(e)

        print("Goto Sleep...")
        epd.sleep()

        print("ctrl + c:")
        epd7in3f.epdconfig.module_exit()

def generate_loop():
    # Wait for Celery, Redis and stuff to boot
    time.sleep(3)

    while True:
        print("Generating a new set of prompts")
        prompts = generate_prompts(3)

        prompts_iter = iter(prompts)
        prompt = next(prompts_iter, None)
        while prompt is not None:
            current_hour = datetime.now().hour
            if app.paused or (current_hour > 1 and current_hour < 10):
                time.sleep(0.5)
                continue

            image_name = Path(f'{uuid.uuid4()}.png')
            image_path = str(Path('generated/') / image_name)

            print("Generating a new image")
            try:
                (seed,) = tasks.generate_image.delay(prompt, image_path).get()
                if (seed is None):
                    raise Exception("Seed is none")
                if (not app.paused):
                    save_result(prompt, seed, image_path)
                    draw_image(image_path)
            except Exception as e:
                print(f"{prompt} failed to generated")
                print(e)
            

            prompt = next(prompts_iter, None)
 

@app.on_event("startup")
def startup():
    res = db.execute("SELECT name from sqlite_master where type='table' and name='prompts'").fetchone()
    if res is None:
        db.execute("CREATE TABLE prompts(prompt, seed, image_path, date)")
        db.commit()

    print("Starting up")
    thread = Thread(target=generate_loop)
    thread.start()

Path("generated").mkdir(exist_ok=True)
Path("uploaded").mkdir(exist_ok=True)

app.mount("/generated", StaticFiles(directory="generated"), name="generated")
app.mount("/uploaded", StaticFiles(directory="uploaded"), name="uploaded")
app.mount("/", StaticFiles(directory="static", html=True), name="static")

