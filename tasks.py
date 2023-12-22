from shlex import quote
import subprocess
import os
import sys
import uuid
import random

from celery import shared_task, chord, Celery
from celery.signals import worker_ready
from celery_singleton import Singleton
from config import settings

celery = Celery(
    __name__,
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND
)

@celery.task(base=Singleton, time_limit=2400)
def generate_image(prompt: str, output_image_path: str):
    seed = random.randint(0, 1000000)
    
    command = f"nice ./sd --rpi-lowmem --turbo --prompt {quote(prompt)} --models-path sdxl-turbo --steps 1 --output {quote(output_image_path)} --seed {seed}"
    #command = f"echo 'hello'; sleep 60; wget https://picsum.photos/800/480 -O {output_image_path}; echo 'end'"
    
    with subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, shell=True) as process:
        #os.system(f"cpulimit --limit 90 {process.pid}")
        while True:
            output_line = process.stdout.readline()
            if output_line == '' and process.poll() is not None:
                break

            print(f"Output: ${output_line.strip()}")

            error_line = process.stderr.readline()
            if error_line == '' and process.poll() is not None:
                break

            print(f"Error: ${error_line.strip()}")

        process.wait()

    return (seed,)
