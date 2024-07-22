import argparse
import hashlib
import json
from base64 import b64decode
import os
from random import shuffle, choice
import time
import tempfile

import requests
import telebot
import pendulum
from openai import OpenAI
from rich import print
import telegramify_markdown


if api_base := os.environ.get("OPENAI_API_BASE"):
    client = OpenAI(base_url=api_base, api_key=os.environ.get("OPENAI_API_KEY"))
else:
    client = OpenAI()

TIMEZONE = "Asia/Shanghai"
KEY = "NDVmZDE3ZTAyMDAzZDg5YmVlN2YwNDZiYjQ5NGRlMTM="
LOGIN_URL = "https://pass.hujiang.com/Handler/UCenter.json?action=Login&isapp=true&language=zh_CN&password={password}&timezone=8&user_domain=hj&username={user_name}"
COVERT_URL = "https://pass-cdn.hjapi.com/v1.1/access_token/convert"

# added in 2023.06.08
XIAOD_LIST_URL = "https://vocablist.hjapi.com/notebook/notebooklist?lastSyncDate=2000-01-01T00%3A00%3A00.000&lastSyncVer=0&syncVer=1"
XIAOD_ONE_NOTE_URL = "https://vocablist.hjapi.com/notebook/notewords?lastSyncDate=2000-01-01T00%3A00%3A00.000&lastSyncVer=0&nbookid={nbook_id}&oldnbookid=0&syncVer=1"


def md5_encode(string):
    m = hashlib.md5()
    m.update(string.encode())
    return m.hexdigest()


####### XIAOD #######
def get_xiaod_notes_dict(s):
    r = s.get(XIAOD_LIST_URL)
    if not r.ok:
        raise Exception("Can not note books info from hujiang")
    d = {}
    node_list = r.json()["data"]["noteList"]
    for n in node_list:
        d[n["nbookId"]] = n["nbookName"]
    return d


def get_xiaod_words(s, nbook_id):
    r = s.get(XIAOD_ONE_NOTE_URL.format(nbook_id=nbook_id))
    if not r.ok:
        raise Exception(f"Can not get words for nbook_id: {nbook_id}")
    return r.json()


def login(user_name, password):
    s = requests.Session()
    password_md5 = md5_encode(password)
    r = s.get(LOGIN_URL.format(user_name=user_name, password=password_md5))
    if not r.ok:
        raise Exception(f"Someting is wrong to login -- {r.text}")
    club_auth_cookie = r.json()["Data"]["Cookie"]
    data = {"club_auth_cookie": club_auth_cookie}
    HJKEY = b64decode(KEY).decode()
    headers = {"hj_appkey": HJKEY, "Content-Type": "application/json"}
    # real login to get real token
    r = s.post(COVERT_URL, headers=headers, data=json.dumps(data))
    if not r.ok:
        raise Exception(f"Get real token failed -- {r.text}")
    access_token = r.json()["data"]["access_token"]
    headers["Access-Token"] = access_token
    s.headers = headers
    return s


def make_xiaod_note(s):
    now = pendulum.now(TIMEZONE)
    note_dict = get_xiaod_notes_dict(s)
    new_words = []
    new_words_define = []
    symbol_list = []
    yesterday_words = []
    yesterday_words_define = []
    yesterday_symbol_list = []

    for k, v in note_dict.items():
        data = get_xiaod_words(s, k)
        word_list = data["data"]["wordList"]
        if not word_list:
            continue
        for word in word_list:
            add_date = word["clientDateUpdated"]
            add_date = pendulum.parse(add_date)
            if add_date.day == now.day and add_date.month == now.month:
                new_words.append(word["word"])
                new_words_define.append(word["definition"])
                symbol_list.append(word["symbol1"])
            if (
                add_date.day == now.subtract(days=1).day
                and add_date.month == now.subtract(days=1).month
            ):
                yesterday_words.append(word["word"])
                yesterday_words_define.append(word["definition"])
                yesterday_symbol_list.append(word["symbol1"])

    if not new_words:
        print("No new words today")
        return yesterday_words, yesterday_words_define, yesterday_symbol_list
    return new_words, new_words_define, symbol_list


def main(user_name, password, token, tele_token, tele_chat_id):
    bot = telebot.TeleBot(tele_token)
    try:
        s = requests.Session()
        HJKEY = b64decode(KEY).decode()
        headers = {"hj_appkey": HJKEY, "Content-Type": "application/json"}
        s.headers = headers
        headers["Access-Token"] = token
        word_list, word_define_list, symbol_list = make_xiaod_note(s)
    except Exception as e:
        bot.send_message(
            tele_chat_id,
            "toekn is invalid, try to login, please change the token in GitHub secret",
        )
        s = login(user_name, password)
        word_list, word_define_list, symbol_list = make_xiaod_note(s)
    # word
    bot.send_message(tele_chat_id, "Today's words:\n" + "\n".join(word_list))
    # symbol
    bot.send_message(tele_chat_id, "Symbol:\n" + "\n".join(symbol_list))
    # define
    bot.send_message(tele_chat_id, "Definition:\n" + "\n".join(word_define_list))
    # ten words combine make a story using openai
    shuffle(word_list)
    words_chunk = [word_list[i : i + 10] for i in range(0, len(word_list), 10)]
    make_story_prompt = "Make a story using these words the story should be written in Japanese words: `{}`, then translate to Chinese."
    for chunk in words_chunk:
        words = ",".join(chunk)
        prompt = make_story_prompt.format(words)
        try:
            completion = client.chat.completions.create(
                messages=[{"role": "user", "content": prompt}],
                model="gpt-4o-2024-05-13",
            )
            head = "Words: " + words + "\n"
            story = completion.choices[0].message.content.encode("utf8").decode()
            audio = client.audio.speech.create(
                model="tts-1",
                voice=choice(["alloy", "echo", "fable", "onyx", "nova", "shimmer"]),
                input=story,
            )
            print("Audio created")
            # make all word in words to be bold
            for word in chunk:
                story = story.replace(word, f"*{word}*")
            # create a temp mp3 file
            with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
                speech_file_path = f.name
                audio.write_to_file(speech_file_path)
                content = head + story
                bot.send_audio(
                    tele_chat_id,
                    open(speech_file_path, "rb"),
                    caption=telegramify_markdown.convert(content),
                )
                # spdier rule
                time.sleep(1)
        except Exception as e:
            print(str(e))
            print("Can not make story")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("user_name", help="hujiang_user_name")
    parser.add_argument("password", help="hujiang_password")
    parser.add_argument("token", help="token", default=None, nargs="?")
    parser.add_argument(
        "--tele_token", help="tele_token", nargs="?", default="", const=""
    )
    parser.add_argument(
        "--tele_chat_id", help="tele_chat_id", nargs="?", default="", const=""
    )
    options = parser.parse_args()
    main(
        options.user_name,
        options.password,
        options.token,
        options.tele_token,
        options.tele_chat_id,
    )
