import argparse
import os
from pathlib import Path
import random
import time

import pendulum
import requests
import telebot
from telebot.types import InputMediaPhoto, InputMediaVideo
from github import Github
from openai import OpenAI
from kling import VideoGen, ImageGen

# 1 real get up #5 for test
GET_UP_ISSUE_NUMBER = 1
GET_UP_MESSAGE_TEMPLATE = "今天的起床时间是--{get_up_time}.\r\n\r\n起床啦。\r\n\r\n今天的一句诗:\r\n{sentence}\r\n"
# in 2024-06-15 this one ssl error
SENTENCE_API = "https://v1.jinrishici.com/all"

DEFAULT_SENTENCE = (
    "赏花归去马如飞\r\n去马如飞酒力微\r\n酒力微醒时已暮\r\n醒时已暮赏花归\r\n"
)
TIMEZONE = "Asia/Shanghai"
YESTERDAY_QUESTION = "问我关于我昨天过的怎么样的五个问题。请不要包含这些问题：{questions}, 并只返回问题。"
if api_base := os.environ.get("OPENAI_API_BASE"):
    client = OpenAI(base_url=api_base, api_key=os.environ.get("OPENAI_API_KEY"))
else:
    client = OpenAI()

KLING_COOKIE = os.environ.get("KLING_COOKIE")


def get_all_til_knowledge_file():
    til_dir = Path(os.environ.get("MORNING_REPO_NAME"))
    today_dir = random.choice(list(til_dir.iterdir()))
    md_files = []
    for root, _, files in os.walk(today_dir):
        for file in files:
            if file.endswith(".md"):
                md_files.append(os.path.join(root, file))
    return md_files


def login(token):
    return Github(token)


def get_one_sentence():
    try:
        r = requests.get(SENTENCE_API)
        if r.ok:
            return r.json()["content"]
        return DEFAULT_SENTENCE
    except:
        print("get SENTENCE_API wrong")
        return DEFAULT_SENTENCE


def get_today_get_up_status(issue):
    comments = list(issue.get_comments())
    if not comments:
        return False, []
    latest_comment = comments[-1]
    now = pendulum.now(TIMEZONE)
    latest_day = pendulum.instance(latest_comment.created_at).in_timezone(
        "Asia/Shanghai"
    )
    is_today = (latest_day.day == now.day) and (latest_day.month == now.month)
    return is_today


def make_pic_and_save(sentence):
    prompt = f"revise `{sentence}` to a stable diffusion prompt"
    try:
        completion = client.chat.completions.create(
            messages=[{"role": "user", "content": prompt}],
            model="gpt-4o-2024-05-13",
        )
        sentence = completion.choices[0].message.content.encode("utf8").decode()
        print(f"revies: {sentence}")
    except:
        print("revise sentence wrong")

    now = pendulum.now()
    date_str = now.to_date_string()
    new_path = os.path.join("OUT_DIR", date_str)
    if not os.path.exists(new_path):
        os.mkdir(new_path)
    # response = client.images.generate(
    #     model="dall-e-3", prompt=sentence, size="1024x1024", quality="standard", n=1
    # )
    # image_url_for_issue = response.model_dump()["data"][0]["url"]
    # response = requests.get(image_url_for_issue)
    # with open(f"{new_path}/1.png", "wb") as f:
    #     f.write(response.content)
    # try to use this to generate video
    i = ImageGen(KLING_COOKIE)
    images_list = i.get_images(sentence)
    return images_list


def make_get_up_message():
    sentence = get_one_sentence()
    now = pendulum.now(TIMEZONE)
    # 3 - 7 means early for me
    is_get_up_early = 3 <= now.hour <= 7
    try:
        images_list = make_pic_and_save(sentence)
    except Exception as e:
        print(str(e))
        # give it a second chance
        try:
            sentence = get_one_sentence()
            print(f"Second: {sentence}")
            images_list = make_pic_and_save(sentence)
        except Exception as e:
            print(str(e))
    return sentence, is_get_up_early, images_list


def get_yesterday_question():
    # get yesterday's questions
    with open("questions.txt") as f:
        questions = f.read()
        print(questions)

    completion = client.chat.completions.create(
        messages=[
            {"role": "user", "content": YESTERDAY_QUESTION.format(questions=questions)}
        ],
        model="gpt-4o-2024-05-13",
    )
    answer = completion.choices[0].message.content.encode("utf8").decode()
    print(answer)
    # write the answer to a file
    with open("questions.txt", "w") as f:
        f.write(answer)
    return answer


def main(
    github_token,
    repo_name,
    weather_message,
    tele_token,
    tele_chat_id,
):
    u = login(github_token)
    repo = u.get_repo(repo_name)
    issue = repo.get_issue(GET_UP_ISSUE_NUMBER)
    is_today = get_today_get_up_status(issue)
    if is_today:
        print("Today I have recorded the wake up time")
        return
    yesterday_question = get_yesterday_question()
    sentence, is_get_up_early, images_list = make_get_up_message()
    get_up_time = pendulum.now(TIMEZONE).to_datetime_string()
    body = GET_UP_MESSAGE_TEMPLATE.format(get_up_time=get_up_time, sentence=sentence)
    early_message = body
    if weather_message:
        weather_message = f"现在的天气是{weather_message}\n"
        body = weather_message + early_message
    body = body + f"\n\n关于昨天的问题？\n{yesterday_question}"
    if is_get_up_early:
        comment = body + f"![image]({images_list[0]})"
        issue.create_comment(comment)
        # send to telegram
        if tele_token and tele_chat_id:
            bot = telebot.TeleBot(tele_token)
            video_caption = ""

            if images_list:
                try:
                    # sleep for waiting for the image to be generated
                    time.sleep(4)
                    photos_list = [InputMediaPhoto(i) for i in images_list[:4]]
                    photos_list[0].caption = body
                    bot.send_media_group(
                        tele_chat_id, photos_list, disable_notification=True
                    )
                    video_caption = "新的一天开始了"
                except Exception as e:
                    print(str(e))
                    video_caption = body
                v = VideoGen(KLING_COOKIE)
                v.save_video(
                    sentence,
                    "./output",
                    image_url=images_list[0],
                    is_high_quality=True,
                )
                bot.send_video(
                    tele_chat_id,
                    open("output/0.mp4", "rb"),  # TODO fix this shit
                    caption=video_caption,
                    disable_notification=True,
                )
    else:
        print("You wake up late")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("github_token", help="github_token")
    parser.add_argument("repo_name", help="repo_name")
    parser.add_argument(
        "--weather_message", help="weather_message", nargs="?", default="", const=""
    )
    parser.add_argument(
        "--tele_token", help="tele_token", nargs="?", default="", const=""
    )
    parser.add_argument(
        "--tele_chat_id", help="tele_chat_id", nargs="?", default="", const=""
    )
    options = parser.parse_args()
    main(
        options.github_token,
        options.repo_name,
        options.weather_message,
        options.tele_token,
        options.tele_chat_id,
    )
