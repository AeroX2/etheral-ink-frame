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

import logging
import numpy as np
from PIL import Image,ImageDraw,ImageFont

if False:
    libdir = os.path.join(os.path.dirname(os.path.dirname(os.path.realpath(__file__))), 'lib')
    if os.path.exists(libdir):
        sys.path.append(libdir)
    from waveshare_epd import epd7in3f

logging.basicConfig(level=logging.DEBUG)

celery = Celery(
    __name__,
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND
)

@celery.task(base=Singleton)
def generate_image(prompt: str, output_image_path: str):
    seed = random.randint(0, 1000000)
    
    if False:
        command = f"./sd --turbo --prompt {quote(prompt)} --models-path sdxlturbo --steps 1 --output {quote(output_image_path)} --seed ${seed}"
    else:
        command = f"echo 'hello'; sleep 3; wget https://cataas.com/cat -O {output_image_path}; echo 'end'"
    
    with subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, shell=True) as process:
        while True:
            output_line = process.stdout.readline()
            if output_line == '' and process.poll() is not None:
                break

            logging.info(f"Output: ${output_line.strip()}")

            error_line = process.stderr.readline()
            if error_line == '' and process.poll() is not None:
                break

            logging.info(f"Error: ${error_line.strip()}")

        process.wait()

    return (seed,)

palette = [
    [0, 0, 0],       # Black
    [0, 0, 255],     # Blue
    [255, 0, 0],     # Red
    [0, 255, 0],     # Green
    [255, 128, 0],   # Orange
    [255, 255, 0],   # Yellow
    [255, 255, 255], # White
]

def find_closest_color(pixel, palette):
    distances = np.linalg.norm(palette - pixel, axis=1)
    return np.argmin(distances)

@celery.task
def dither_image(image_path: str, output_path: str):
    # Open the image
    input_image = Image.open(image_path)

    palette_expand = [x for t in palette for x in t]
    paletteim = Image.new('P', (16,16))
    paletteim.putpalette(palette * 32)

    dithered_image = input_image.quantize(colors=7, palette=paletteim)
    dithered_image.save(output_path, "BMP")

@celery.task
def draw_image(file_path: str):
    try:
        epd = epd7in3f.EPD()
        logging.info("init and Clear")
        epd.init()
        epd.Clear()

        with Image.open(file_path) as image:
            epd.display(epd.getbuffer(image))
            epd.sleep()

    except Exception as e:
        logging.info("Goto Sleep...")
        epd.sleep()

        logging.info("ctrl + c:")
        epd7in3f.epdconfig.module_exit()

        logging.info(e)
