import argparse
import os
from pathlib import Path
import random

import pendulum
import requests
import telebot
from github import Github
from openai import OpenAI
import telegramify_markdown

# 1 real get up #5 for test
GET_UP_ISSUE_NUMBER = 1
GET_UP_MESSAGE_TEMPLATE = "今天的起床时间是--{get_up_time}.\r\n\r\n 起床啦。\r\n\r\n 今天的一句诗:\r\n {sentence} \r\n"
# in 2024-06-15 this one ssl error
SENTENCE_API = "https://v1.jinrishici.com/all"
SENTENCE_API = (
    "https://api.sou-yun.cn/api/RecommendedReading?type=poem&needHtml=true&index=-1"
)
DEFAULT_SENTENCE = (
    "赏花归去马如飞\r\n去马如飞酒力微\r\n酒力微醒时已暮\r\n醒时已暮赏花归\r\n"
)
TIMEZONE = "Asia/Shanghai"
if api_base := os.environ.get("OPENAI_API_BASE"):
    client = OpenAI(base_url=api_base, api_key=os.environ.get("OPENAI_API_KEY"))
else:
    client = OpenAI()


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


def get_one_sentence(up_list):
    try:
        r = requests.get(SENTENCE_API)
        if r.ok:
            content = ""
            concent_list = r.json()["Content"]["Poem"]["Clauses"]
            for c in concent_list:
                content += c["Content"] + "\r\n"
            return content
        return DEFAULT_SENTENCE
    except:
        print("get SENTENCE_API wrong")
        return DEFAULT_SENTENCE


def get_today_get_up_status(issue):
    comments = list(issue.get_comments())
    if not comments:
        return False, []
    up_list = []
    for comment in comments:
        try:
            s = comment.body.splitlines()[6]
            up_list.append(s)
        except Exception as e:
            print(str(e), "!!")
            continue
    latest_comment = comments[-1]
    now = pendulum.now(TIMEZONE)
    latest_day = pendulum.instance(latest_comment.created_at).in_timezone(
        "Asia/Shanghai"
    )
    is_today = (latest_day.day == now.day) and (latest_day.month == now.month)
    return is_today, up_list


def make_pic_and_save(sentence):
    prompt = f"revise `{sentence}` to a stable diffusion prompt"
    try:
        completion = client.chat.completions.create(
            messages=[{"role": "user", "content": prompt}],
            model="gpt-4-1106-preview",
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
    response = client.images.generate(
        model="dall-e-3", prompt=sentence, size="1024x1024", quality="standard", n=1
    )
    image_url_for_issue = response.model_dump()["data"][0]["url"]
    response = requests.get(image_url_for_issue)
    with open(f"{new_path}/1.png", "wb") as f:
        f.write(response.content)
    # try to use this to generate video
    try:
        from luma import VideoGen

        cookie = os.environ.get("LUMA_COOKIE")
        v = VideoGen(cookie, f"{new_path}/1.png")
        video_path = v.save_video(sentence, new_path)
        return image_url_for_issue, video_path
    except Exception as e:
        print("No luma")
        print(str(e))
    return image_url_for_issue, None


def make_get_up_message(up_list):
    sentence = get_one_sentence(up_list)
    now = pendulum.now(TIMEZONE)
    # 3 - 7 means early for me
    is_get_up_early = 3 <= now.hour <= 7
    get_up_time = now.to_datetime_string()
    link_for_issue = ""
    video_path = None
    try:
        link_for_issue, video_path = make_pic_and_save(sentence)
    except Exception as e:
        print(str(e))
        # give it a second chance
        try:
            sentence = get_one_sentence(up_list)
            print(f"Second: {sentence}")
            link_for_issue, video_path = make_pic_and_save(sentence)
        except Exception as e:
            print(str(e))
    body = GET_UP_MESSAGE_TEMPLATE.format(get_up_time=get_up_time, sentence=sentence)
    print(body, link_for_issue, video_path)
    return body, is_get_up_early, link_for_issue, video_path


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
    is_today, up_list = get_today_get_up_status(issue)
    if is_today:
        print("Today I have recorded the wake up time")
        return
    early_message, is_get_up_early, link_for_issue, video_path = make_get_up_message(
        up_list
    )
    body = early_message
    if weather_message:
        weather_message = f"现在的天气是{weather_message}\n"
        body = weather_message + early_message
    if is_get_up_early:
        # with open("knowledge.txt") as f:
        #     all_my_knowledge_list = list(f.read().splitlines())
        # til_mds_list = get_all_til_knowledge_file()
        # file_name = None
        # if til_mds_list:
        #     while True:
        #         file_name = random.choice(til_mds_list)
        #         if file_name not in all_my_knowledge_list:
        #             break
        #     with open("knowledge.txt", "a") as f:
        #         f.write(f"{file_name}\n")
        comment = body + f"![image]({link_for_issue})"
        issue.create_comment(comment)
        # send to telegram
        if tele_token and tele_chat_id:
            bot = telebot.TeleBot(tele_token)
            if link_for_issue:
                if video_path:
                    bot.send_video(
                        tele_chat_id,
                        open(video_path, "rb"),
                        caption=body,
                        disable_notification=True,
                    )
                else:
                    try:
                        bot.send_photo(
                            tele_chat_id,
                            link_for_issue,
                            caption=body,
                            disable_notification=True,
                        )
                    except:
                        pass
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
