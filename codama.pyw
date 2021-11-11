from linebot import (
   LineBotApi, WebhookHandler
)
from linebot.exceptions import (
   LineBotApiError
)
from linebot.models import (
   TextMessage, TextSendMessage,
)

import os
import sys
import RPi.GPIO as GPIO
import paho.mqtt.client as mqtt
import requests
import json
import cv2
import asyncio
import time
import numpy as np
import itertools
from pydub import AudioSegment
from pydub.playback import play
import threading
from PIL import ImageFont, ImageDraw, Image

IMAGE_FOLDER_PATH = "./image"
JPG_BG_PATH = os.path.join(IMAGE_FOLDER_PATH, "background.jpg")
GIF_SUMMON_PATH = os.path.join(IMAGE_FOLDER_PATH, "summon.gif")
GIF_ALPHA_POSI_PATH = os.path.join(IMAGE_FOLDER_PATH, "kodama.gif")
GIF_NEGA_PATH = os.path.join(IMAGE_FOLDER_PATH, "mononoke_inu.gif")
GIF_NEGAPOSHI_PATH = os.path.join(IMAGE_FOLDER_PATH, "kodama_many.gif")
CV_WIN_TITLE = "win"

CHANNEL_ACCESS_TOKEN = os.environ["CHANNEL_ACCESS_TOKEN"]
CHANNEL_SECRET = os.environ["CHANNEL_SECRET"]
BEEBOTTE_TOKEN = os.environ["BEEBOTTE_TOKEN"]
NEGAPOSI_KEY = os.environ["NEGAPOSI_KEY"]

line_bot_api = LineBotApi(CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(CHANNEL_SECRET)
client = mqtt.Client()

# codamaのwake up wordが検出されるとhighになるGPIO
CODAMA_TRIGGERD_GPIO = 27

def meature_negaposi(text):
    if not text:
        return 0
    params = {'out': 'json', 'apikey': NEGAPOSI_KEY, 'text': text}
    response = requests.post('http://ap.mextractr.net/negaposi_measure', params = params)
    if response.status_code != requests.codes.ok:
        line_bot_api.push_message(os.environ["USER_ID"], TextSendMessage(text="パブリッシュの作成に失敗しました"))
    res_json = response.json()

    if 'negaposi' in res_json:
        return res_json["negaposi"]
    return 0

def show_return_message_image(val):
    if val > 0:
        asyncio.run(show_giffile(GIF_ALPHA_POSI_PATH, loop = False, wait_time = 70))
    elif val < 0:
        asyncio.run(show_giffile(GIF_NEGA_PATH, loop = False, display_time = 5))
    else:
        asyncio.run(show_giffile(GIF_NEGAPOSHI_PATH, loop = False, wait_time = 100))

def on_message(client, userdata, msg):
    msg_json = json.loads(msg.payload)
    if 'data' in msg_json:
        print(msg_json["data"])
    else:
        print("LINEを確認してみて")

    show_return_message_image(meature_negaposi(msg_json["data"]))

    # point = (30, 450)
    threading.Thread(target=show_message, args=(msg_json["data"], )).start()

def on_connect(client, userdata, flag, rc):
    client.subscribe('kodama_return/return_msg')
    print("Connected with result code " + str(rc))

def on_disconnect(client, userdata, flag, rc):
  if rc != 0:
      print("Unexpected disconnection.")

##############################

def codama_setup():
    GPIO.setmode(GPIO.BCM)
    GPIO.setup(CODAMA_TRIGGERD_GPIO, GPIO.IN)
    # 立ち上がりエッジ検出をチャネルに加える
    GPIO.add_event_detect(CODAMA_TRIGGERD_GPIO, GPIO.RISING)
    GPIO.add_event_callback(CODAMA_TRIGGERD_GPIO, callback=detected_callback)

def detected_callback(value):
    # wake up wordを検出したら、Sebastienの音声入力をONにする
    try:
        line_bot_api.push_message(os.environ["USER_ID"], TextSendMessage(text='お疲れ様です'))
        line_bot_api.push_message(os.environ["USER_ID"], TextSendMessage(text='たすけてください!!!!'))
        print("detected_callback")

        sound = AudioSegment.from_file("kodama_audio.m4a")
        th = threading.Thread(target=play, args=(sound,))
        # th2 = threading.Thread(target=show_giffile, args=(GIF_SUMMON_PATH, True, 6, 0))
        th.start()
        time.sleep(2)
        asyncio.run(show_giffile(GIF_SUMMON_PATH, display_time = 6))
        # th2.start()
        # th2.join()
        show_image_fullscreen(JPG_BG_PATH)

        # asyncio.run(play_sound("kodama_audio.m4a"))



        # asyncio.run(kodama_karakara())

    except LineBotApiError as e:
        print(e.status_code)
        print(e.request_id)
        print(e.error.message)
        print(e.error.details)

def cleanup():
    print ("cleanup")
    GPIO.cleanup()

##############################

async def show_giffile(file_path, loop = True, display_time = 3, wait_time = 0):
    cap = cv2.VideoCapture(file_path)

    fps = cap.get(cv2.CAP_PROP_FPS)
    if wait_time <= 0:
        wait_time = int(1000/fps)

    images = []
    i = 0
    while True:
        ret_success, frame = cap.read()
        if not ret_success:
            break

        images.append(frame)
        i += 1

    if loop == True:
        datas_iterator = itertools.cycle(images)
        start_time = time.time()
        for (n, data) in enumerate(datas_iterator):
            # 要素を表示
            cv2.imshow(CV_WIN_TITLE, data)
            cv2.waitKey(wait_time)  # １コマを表示するミリ秒
            # 上限を指定してbreak
            if time.time() - start_time > display_time:
                break
            if n >= 100:
                break
    else:
        start_time = time.time()
        for index in range(len(images)):
            cv2.imshow(CV_WIN_TITLE, images[index])
            cv2.waitKey(wait_time)  # １コマを表示するミリ秒
            if time.time() - start_time > display_time:
                break

    cap.release()

async def count_sleep_time(sec = 3):
    loop = asyncio.get_event_loop()
    print(f'start:  {sec}秒待つよ')
    await asyncio.sleep(sec)
    print(f'finish: {sec}秒待ったよ')

##############################

def show_message(message, display_time = 3, image_path = JPG_BG_PATH, point = (30, 30), font_path = "mplus-1m-regular.otf", font_size = 100, color=(255,255,255)):
    image = show_image_fullscreen(image_path)
    image = put_text(image, message, point, font_path, font_size, color)


    start_time = time.time()
    while time.time() - start_time < display_time:
        cv2.imshow(CV_WIN_TITLE, image)
        cv2.waitKey(500)

    show_image_fullscreen(JPG_BG_PATH)
    cv2.waitKey(500)

    return

def show_image_fullscreen(image_path, window_name = CV_WIN_TITLE):
    img = cv2.imread(image_path)
    img = cv2.resize(img, (1024, 600))

    cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)
    cv2.setWindowProperty(window_name, cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_FULLSCREEN)
    cv2.imshow(window_name, img)

    return img

def put_text(bk_image, text, point, font_path = "mplus-1m-regular.otf", font_size = 100, color=(0,0,0)):
    font = ImageFont.truetype(font_path, font_size)

    cv_rgb_image = cv2.cvtColor(bk_image, cv2.COLOR_BGR2RGB)
    img_pil = Image.fromarray(cv_rgb_image)
    draw = ImageDraw.Draw(img_pil)
    draw.text(point, text, fill=color, font=font)
    img_array = np.asarray(img_pil)

    return cv2.cvtColor(img_array, cv2.COLOR_RGB2BGR)

##############################

if __name__ == "__main__":
    try:
        codama_setup()

        show_image_fullscreen(JPG_BG_PATH)

        client.on_connect = on_connect
        client.on_disconnect = on_disconnect
        client.on_message = on_message

        client.username_pw_set("token:" + BEEBOTTE_TOKEN)
        client.tls_set("./mqtt.beebotte.com.pem")
        client.connect("mqtt.beebotte.com", 8883, 60)

        # client.loop_forever()
        client.loop_start()

        cv2.waitKey(0)
        client.disconnect()
    except Exception as e:
        cv2.destroyAllWindows()
        client.disconnect()
        cleanup()
        print("error message:{0}".format(e.with_traceback(sys.exc_info()[2])))
        exit(0)
