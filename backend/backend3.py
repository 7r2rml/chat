from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pymongo import MongoClient
from typing import Dict
from datetime import datetime, timedelta
import uvicorn
import json
import base64
import io
from pydantic import BaseModel
from openai import OpenAI
from bson import json_util
from fastapi.responses import JSONResponse
from gtts import gTTS
import requests
from google.oauth2 import service_account
from googleapiclient.discovery import build
import pytz
from datetime import datetime, timezone, timedelta
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
import os.path

SCOPES = ['https://www.googleapis.com/auth/calendar']
TOKEN_FILE = 'token.json'
CREDS_FILE = 'credentials.json'
kst = pytz.timezone('Asia/Seoul')

# ✅ OpenAI 키 설정
client = OpenAI(api_key=openai_api_key)

# ✅ FastAPI 초기화
app = FastAPI()
origins = ["http://localhost:3000"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ✅ MongoDB 연결
mongoclient = MongoClient("mongodb://localhost:27017")
db = mongoclient.chat_db
messages_collection = db.messages

# ✅ 연결 관리 클래스
class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[str, WebSocket] = {}

    async def connect(self, websocket: WebSocket, nickname: str):
        await websocket.accept()
        self.active_connections[nickname] = websocket

    def disconnect(self, nickname: str):
        self.active_connections.pop(nickname, None)

    async def broadcast(self, message: dict):
        for connection in self.active_connections.values():
            await connection.send_json(message)

manager = ConnectionManager()

# ✅ Google Calendar 서비스 초기화 함수
def get_calendar_service():
    SCOPES = ['https://www.googleapis.com/auth/calendar']
    CREDS_FILE = "client_secret_772705558537-6h8m52vucq7hpv0r2pggt71dqq6ubb8p.apps.googleusercontent.com.json"  # 실제 경로로 교체 필요
    if os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
    else:
        flow = InstalledAppFlow.from_client_secrets_file(CREDS_FILE, SCOPES)
        creds = flow.run_local_server(port=0)
        with open(TOKEN_FILE, 'w') as token:
            token.write(creds.to_json())
    return build('calendar', 'v3', credentials=creds)


    return build('calendar', 'v3', credentials=credentials)

# ✅ @calender 명령어 처리 함수
async def handle_calendar_command(text: str, nickname: str) -> str:
    try:
        parts = text.replace("@calendar", "").strip()

        time = datetime.now(kst).isoformat()
        system_msg = {
            "role": "system",
            "content": (
                f'''당신은 사용자의 일정 요청을 분석해 JSON 형식으로 응답하는 일정 파서입니다.
                        기준이 되는 현재시간은 다음과 같습니다 {time}
                        형식은 다음과 같습니다 :
                        {{"action":"create" "update" "delete" ,
                        "title": "민혁이랑 저녁 약속",
                        "datetime" : "2025-08-05T13:00:00",
                        "new_datetime" : "2025-08-05T15:00:00"
                        }}
                        오직 JSON으로만 응답해줘.'''
            )
        }

        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                system_msg,
                {"role": "user", "content": parts}]
        )
        gpt_reply = response.choices[0].message.content.strip()
        print("[GPT 응답]", gpt_reply)

        try:
            event_data = json.loads(gpt_reply)
        except json.JSONDecodeError as e:
            print("[JSON 파싱 실패",e)
            return "GPT 응답을 이해할 수 없습니다."

        service = get_calendar_service()

        if event_data["action"] == "create":
            event = {
                'summary': event_data["title"],
                'start': {
                    'dateTime': event_data["datetime"],
                    'timeZone': 'Asia/Seoul',
                },
                'end': {
                    'dateTime': (
                            datetime.fromisoformat(event_data["datetime"]) + timedelta(hours=1)
                    ).isoformat(),
                    'timeZone': 'Asia/Seoul',
                },
            }
            created_event = service.events().insert(calendarId='primary', body=event).execute()

            return f"✅ 일정이 등록되었습니다: {created_event['summary']} at {created_event['start']['dateTime']}"

        else:
            return "⚠️ 현재는 'create' 일정 추가만 지원합니다."

    except Exception as e:
        print(f"[Calendar Error] {e}")
        return "❌ 일정 추가에 실패했습니다. 형식을 확인해주세요."


        # title = " ".join(parts[:-2])
        # date_str = parts[-2]
        # time_str = parts[-1]
        # start_datetime = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
        #
        # event = {
        #     'summary': title,
        #     'start': {'dateTime': start_datetime.isoformat(), 'timeZone': 'Asia/Seoul'},
        #     'end': {'dateTime': (start_datetime + timedelta(hours=1)).isoformat(), 'timeZone': 'Asia/Seoul'},
        # }
        #
        # service = get_calendar_service()
        # result = service.events().insert(calendarId='primary', body=event).execute()
        #
        # return f"✅ 일정 등록 완료: {result.get('summary')} - {result.get('start').get('dateTime')}"


# ✅ 텍스트를 음성(base64)으로 변환
def text_to_audio_base64(text: str) -> str:
    tts = gTTS(text=text, lang="ko")
    buffer = io.BytesIO()
    tts.write_to_fp(buffer)
    buffer.seek(0)
    return base64.b64encode(buffer.read()).decode("utf-8")

# ✅ 이미지 생성 (DALL·E)
async def generate_image_base64(prompt: str) -> str:
    try:
        response = client.images.generate(
            model="dall-e-3",
            prompt=prompt,
            n=1,
            size="1024x1024"
        )
        image_url = response.data[0].url
        image_response = requests.get(image_url)
        return base64.b64encode(image_response.content).decode("utf-8")
    except Exception as e:
        print(f"[Image Error] {e}")
        return ""

# ✅ 음성 → 텍스트 변환
async def transcribe_audio_openai(audio_bytes: bytes) -> str:
    try:
        response = client.audio.transcriptions.create(
            file=io.BytesIO(audio_bytes),
            model="whisper-1",
            language="ko"
        )
        return response.text
    except Exception as e:
        print(f"[STT 오류] {e}")
        return ""

# ✅ GPT 응답 생성
async def get_gpt_response(user_input: str) -> str:
    try:
        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "당신은 친절한 챗봇입니다."},
                {"role": "user", "content": user_input}
            ]
        )
        return response.choices[0].message.content
    except Exception as e:
        return f"⚠️ GPT 오류: {str(e)}"

# ✅ WebSocket 핸들러
@app.websocket("/ws/{nickname}")
async def websocket_endpoint(websocket: WebSocket, nickname: str):
    await manager.connect(websocket, nickname)
    try:
        while True:
            raw_data = await websocket.receive_text()
            try:
                data = json.loads(raw_data)
            except json.JSONDecodeError:
                print("Invalid JSON:", raw_data)
                continue

            timestamp = datetime.utcnow()
            data["timestamp"] = timestamp.isoformat()
            msg_type = data.get("type")
            message_text = data.get("message", "").strip()

            # ✅ @calender 처리
            if msg_type == "text" and message_text.startswith("@calendar"):
                response_msg = await handle_calendar_command(message_text, nickname)
                response = {
                    "type": "text",
                    "nickname": "Calendar",
                    "message": response_msg,
                    "timestamp": datetime.utcnow().isoformat()
                }
                await manager.broadcast(response)
                messages_collection.insert_one(response)
                continue

            # ✅ @tts
            if msg_type == "text" and message_text.startswith("@tts"):
                tts_text = message_text.replace("@tts", "").strip()
                if not tts_text:
                    await websocket.send_json({
                        "type": "text",
                        "nickname": "system",
                        "message": "변환할 텍스트가 없습니다.",
                        "timestamp": datetime.utcnow().isoformat()
                    })
                    continue

                base64_audio = text_to_audio_base64(tts_text)
                payload = {
                    "type": "audio",
                    "nickname": nickname,
                    "message": tts_text,
                    "audioData": base64_audio,
                    "timestamp": datetime.utcnow().isoformat()
                }
                await manager.broadcast(payload)
                messages_collection.insert_one(payload)
                continue

            # ✅ 음성 처리
            if msg_type == "audio":
                mode = data.get("mode", "")
                b64_audio = data.get("audioData", "")
                if not b64_audio:
                    continue
                audio_bytes = base64.b64decode(b64_audio)

                if mode == "@stt":
                    text = await transcribe_audio_openai(audio_bytes)
                    response = {
                        "type": "text",
                        "nickname": "STT",
                        "message": text,
                        "timestamp": datetime.utcnow().isoformat()
                    }
                    await manager.broadcast(response)
                    messages_collection.insert_one(response)

                elif mode == "@talk":
                    text = await transcribe_audio_openai(audio_bytes)
                    gpt_res = await get_gpt_response(text)
                    base64_audio = text_to_audio_base64(gpt_res)

                    await manager.broadcast({
                        "type": "text",
                        "nickname": "GPT",
                        "message": gpt_res,
                        "timestamp": datetime.utcnow().isoformat()
                    })
                    await manager.broadcast({
                        "type": "audio",
                        "nickname": "GPT",
                        "message": gpt_res,
                        "audioData": base64_audio,
                        "timestamp": datetime.utcnow().isoformat()
                    })
                continue

            # ✅ 이미지 생성
            if msg_type == "text" and message_text.startswith("@image"):
                prompt = message_text.replace("@image", "").strip()
                if not prompt:
                    await websocket.send_json({
                        "type": "text",
                        "nickname": "system",
                        "message": "이미지를 생성할 프롬프트가 없습니다.",
                        "timestamp": datetime.utcnow().isoformat()
                    })
                    continue

                base64_img = await generate_image_base64(prompt)
                if not base64_img:
                    await websocket.send_json({
                        "type": "text",
                        "nickname": "system",
                        "message": "이미지 생성에 실패했습니다.",
                        "timestamp": datetime.utcnow().isoformat()
                    })
                    continue

                await manager.broadcast({
                    "type": "image",
                    "nickname": nickname,
                    "message": prompt,
                    "imageData": base64_img,
                    "timestamp": datetime.utcnow().isoformat()
                })
                continue

            # ✅ 일반 텍스트 처리
            if msg_type == "text":
                await manager.broadcast(data)
                gpt_res = await get_gpt_response(message_text)
                gpt_message = {
                    "type": "text",
                    "nickname": "GPT",
                    "message": gpt_res,
                    "timestamp": datetime.utcnow().isoformat()
                }
                await manager.broadcast(gpt_message)
                messages_collection.insert_one(gpt_message)

    except WebSocketDisconnect:
        manager.disconnect(nickname)
        await manager.broadcast({
            "nickname": "system",
            "message": f"{nickname}님이 나갔습니다.",
            "timestamp": datetime.utcnow().isoformat()
        })

# ✅ 서버 실행
if __name__ == "__main__":
    uvicorn.run("backend3:app", host="0.0.0.0", port=8000, reload=True)
