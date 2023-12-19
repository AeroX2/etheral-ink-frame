from shlex import quote
from pathlib import Path
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
def generate_image(prompt: str, output_image_path: Path):
    path = Path(output_image_path)
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

palette = np.array([
    [0, 0, 0],       # Black
    [0, 0, 255],     # Blue
    [255, 0, 0],     # Red
    [0, 255, 0],     # Green
    [255, 128, 0],   # Orange
    [255, 255, 0],   # Yellow
    [255, 255, 255], # White
])

def find_closest_color(pixel, palette):
    distances = np.linalg.norm(palette - pixel, axis=1)
    return np.argmin(distances)

@celery.task
def dither_image(image_path: Path, output_path: Path):
    with Image.open(image_path) as image:
        img_array = np.array(image)

        # Normalize pixel values to the range [0, 1]
        img_array = img_array / 255.0

        # Apply Floyd-Steinberg dithering using the specified palette
        for y in range(img_array.shape[0] - 1):
            for x in range(1, img_array.shape[1] - 1):
                old_pixel = img_array[y, x]
                new_pixel_index = find_closest_color(old_pixel, palette)
                new_pixel = palette[new_pixel_index]
                img_array[y, x] = new_pixel
                error = old_pixel - new_pixel

                img_array[y, x + 1] += error * 7 / 16
                img_array[y + 1, x - 1] += error * 3 / 16
                img_array[y + 1, x] += error * 5 / 16
                img_array[y + 1, x + 1] += error * 1 / 16

        dithered_image = Image.fromarray((img_array * 255).astype(np.uint8))
        dithered_image.save(output_path, "PNG")

@celery.task
def draw_image(file_path: Path):
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
