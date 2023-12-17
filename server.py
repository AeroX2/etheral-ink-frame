from typing import Union
from fastapi import FastAPI, BackgroundTasks

import uuid
import tasks

app = FastAPI()

@app.get("/")
def root():
    return {"Hello": "World"}

@app.get("/generate")
def generate(prompt: str):
    tasks.generate_image.delay(prompt, "generated/{}.png".format(uuid.uuid4()))
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

@app.get("/prompts")
def prompts():
    print(tasks.db.execute("SELECT * from prompts"))
