from flask import Flask, request, abort

from linebot import (
   LineBotApi, WebhookHandler
)
from linebot.exceptions import (
   InvalidSignatureError
)
from linebot.models import (
   MessageEvent, TextMessage, TextSendMessage,
)

import os
import logging
import sys
import requests
import json

app = Flask(__name__)

app.logger.addHandler(logging.StreamHandler(sys.stdout))

CHANNEL_ACCESS_TOKEN = os.environ["CHANNEL_ACCESS_TOKEN"]
CHANNEL_SECRET = os.environ["CHANNEL_SECRET"]
BEEBOTTE_TOKEN = os.environ['BEEBOTTE_TOKEN']

line_bot_api = LineBotApi(CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(CHANNEL_SECRET)

@app.route("/")
def hello_world():
    return "hello world!"

@app.route("/callback", methods=['POST'])
def callback():
    # get X-Line-Signature header value
    signature = request.headers['X-Line-Signature']

    # get request body as text
    body = request.get_data(as_text=True)
    app.logger.info("Request body: " + body)

    # handle webhook body
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        print("Invalid signature. Please check your channel access token/channel secret.")
        abort(400)

    return 'OK'

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    params = {'token': BEEBOTTE_TOKEN}
    headers = {'Content-Type': 'application/json'}
    data = json.dumps({"data": event.message.text})
    response = requests.post('https://api.beebotte.com/v1/data/publish/kodama_return/return_msg', params = params, headers=headers, data=data)
    if response.status_code != requests.codes.ok:
        line_bot_api.push_message(os.environ["USER_ID"], TextSendMessage(text="パブリッシュの作成に失敗しました" + " statuscode : " + response.status_code))

if __name__ == "__main__":
    try:
        port = int(os.getenv("PORT"))
        app.run(debug=False, host="0.0.0.0", port=port)
    except Exception as e:
        print(e.message)
        exit(0)
