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
import copy
import argparse
import RPi.GPIO as GPIO
import paho.mqtt.client as mqtt
import requests
import json
import cv2
import asyncio
import time
import numpy as np
import threading
import itertools
from pydub import AudioSegment
from pydub.playback import play
from PIL import ImageFont, ImageDraw, Image
import signal
import mediapipe as mp
from utils import CvFpsCalc

import datetime

IMAGE_FOLDER_PATH = "./images"
JPG_BG_PATH = os.path.join(IMAGE_FOLDER_PATH, "background.jpg")
GIF_SUMMON_PATH = os.path.join(IMAGE_FOLDER_PATH, "summon.gif")
GIF_ALPHA_POSI_PATH = os.path.join(IMAGE_FOLDER_PATH, "kodama.gif")
GIF_NEGA_PATH = os.path.join(IMAGE_FOLDER_PATH, "mononoke_inu.gif")
GIF_NEGAPOSHI_PATH = os.path.join(IMAGE_FOLDER_PATH, "kodama_many.gif")
CV_WIN_TITLE = "win"
LINE_MESSAGE_FILE = "LineMessage.txt"

CHANNEL_ACCESS_TOKEN = os.environ["CHANNEL_ACCESS_TOKEN"]
CHANNEL_SECRET = os.environ["CHANNEL_SECRET"]
BEEBOTTE_TOKEN = os.environ["BEEBOTTE_TOKEN"]
NEGAPOSI_KEY = os.environ["NEGAPOSI_KEY"]

line_bot_api = LineBotApi(CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(CHANNEL_SECRET)
client = mqtt.Client()

# codamaのwake up wordが検出されるとhighになるGPIO
CODAMA_TRIGGERD_GPIO = 27
# GIFファイル表示中フラグ
SHOW_GIF = False

##############################
## 定期実行 Thread
##############################
class setInterval:
    def __init__(self,interval,action,args) :
        self.interval  = interval
        self.action    = action
        self.stopEvent = threading.Event()
        self.args      = args
        thread         = threading.Thread(target=self.__setInterval)
        thread.start()

    def __setInterval(self):
        nextTime = time.time()+self.interval
        while not self.stopEvent.wait(nextTime-time.time()):
            nextTime += self.interval
            threading.Thread(target=self.action, args=self.args).start()

    def cancel(self):
        self.stopEvent.set()

##############################
## media pipe
##############################
def capture_hand_from_webcamera(cap, hands, cvFpsCalc):
    global show_pre_message

    display_fps = cvFpsCalc.get()

    # カメラキャプチャ #####################################################
    ret, image = cap.read()
    if not ret:
        print("not cap read")
        return
    image = cv2.flip(image, 1)  # ミラー表示
    debug_image = copy.deepcopy(image)

    # 検出実施 #############################################################
    image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
    results = hands.process(image)

    # 描画 ################################################################
    if results.multi_hand_landmarks is not None:
        if show_pre_message == False:
            try:
                file = open(LINE_MESSAGE_FILE, 'r')
                show_message(file.read(), display_time=1)
                file.close()
            except Exception as e:
                print("error message:{0}".format(e.with_traceback(sys.exc_info()[2])))


##############################
## negaposi
##############################

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
    print("on_message")
    msg_json = json.loads(msg.payload)
    if 'data' in msg_json:
        print(msg_json["data"])
    else:
        print("LINEを確認してみて")

    show_return_message_image(meature_negaposi(msg_json["data"]))
    # point = (30, 450)
    threading.Thread(target=show_message, args=(msg_json["data"], )).start()

    file = open(LINE_MESSAGE_FILE, 'w')
    file.write(msg_json["data"])
    file.close()

def on_connect(client, userdata, flag, rc):
    print("on_connect")
    client.subscribe('kodama_return/return_msg')
    print("Connected with result code " + str(rc))

def on_disconnect(client, userdata, rc):
    print("on_disconnect")
    if rc != 0:
        print("Unexpected disconnection.")

##############################
## codama
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
        threading.Thread(target=play, args=(sound,)).start()
        time.sleep(2)
        asyncio.run(show_giffile(GIF_SUMMON_PATH, display_time = 6))
        show_image_fullscreen(JPG_BG_PATH)

    except LineBotApiError as e:
        print(e.status_code)
        print(e.request_id)
        print(e.error.message)
        print(e.error.details)

def cleanup():
    print ("cleanup")
    GPIO.cleanup()

##############################
## gif
##############################
async def show_giffile(file_path, loop = True, display_time = 3, wait_time = 0):
    SHOW_GIF = True
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
    SHOW_GIF = False

##############################
## opencv
##############################

def show_message(message, display_time = 3, image_path = JPG_BG_PATH, point = (30, 30), font_path = "mplus-1m-regular.otf", font_size = 100, color=(255,255,255)):
    show_pre_message = True
    image = show_image_fullscreen(image_path)
    image = put_text(image, message, point, font_path, font_size, color)

    start_time = time.time()
    while time.time() - start_time < display_time:
        cv2.imshow(CV_WIN_TITLE, image)
        cv2.waitKey(500)

    show_image_fullscreen(JPG_BG_PATH)
    cv2.waitKey(500)
    show_pre_message = False
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
## common
##############################

async def count_sleep_time(sec = 3):
    loop = asyncio.get_event_loop()
    print(f'start:  {sec}秒待つよ')
    await asyncio.sleep(sec)
    print(f'finish: {sec}秒待ったよ')

def get_args():
    parser = argparse.ArgumentParser()

    parser.add_argument("--device", type=int, default=0)
    parser.add_argument("--width", help='cap width', type=int, default=960)
    parser.add_argument("--height", help='cap height', type=int, default=540)

    parser.add_argument("--max_num_hands", type=int, default=2)
    parser.add_argument("--min_detection_confidence",
                        help='min_detection_confidence',
                        type=float,
                        default=0.7)
    parser.add_argument("--min_tracking_confidence",
                        help='min_tracking_confidence',
                        type=int,
                        default=0.5)

    parser.add_argument('--use_brect', action='store_true')

    args = parser.parse_args()

    return args

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

        ## --------------------

        args = get_args()

        cap_device = args.device
        cap_width = args.width
        cap_height = args.height

        max_num_hands = args.max_num_hands
        min_detection_confidence = args.min_detection_confidence
        min_tracking_confidence = args.min_tracking_confidence

        use_brect = args.use_brect

        # カメラ準備
        camera_cap = cv2.VideoCapture(cap_device)
        camera_cap.set(cv2.CAP_PROP_FRAME_WIDTH, cap_width)
        camera_cap.set(cv2.CAP_PROP_FRAME_HEIGHT, cap_height)

        # モデルロード
        mp_hands = mp.solutions.hands
        hands = mp_hands.Hands(
            max_num_hands=max_num_hands,
            min_detection_confidence=min_detection_confidence,
            min_tracking_confidence=min_tracking_confidence,
        )

        # FPS計測モジュール
        cvFpsCalc = CvFpsCalc(buffer_len=10)

        show_pre_message = False
        inter=setInterval(0.5,capture_hand_from_webcamera,args=(camera_cap, hands, cvFpsCalc,))

        cv2.waitKey(0)

        client.disconnect()
    except Exception as e:
        cv2.destroyAllWindows()
        client.disconnect()
        cleanup()
        print("error message:{0}".format(e.with_traceback(sys.exc_info()[2])))
        exit(0)
