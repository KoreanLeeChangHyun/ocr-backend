import os
from fastapi import FastAPI, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from google.cloud import vision
from openai import OpenAI
from dotenv import load_dotenv
from PIL import Image
import io
from typing import List
from mangum import Mangum
import boto3
import json
import base64

# 환경 변수 로드
load_dotenv()

app = FastAPI()
handler = Mangum(app)

# CORS 설정
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def get_secret(secret_name):
    session = boto3.session.Session()
    client = session.client(
        service_name='secretsmanager',
        region_name=os.getenv('AWS_REGION', 'ap-northeast-2')
    )
    
    try:
        get_secret_value_response = client.get_secret_value(
            SecretId=secret_name
        )
    except Exception as e:
        raise e
    else:
        if 'SecretString' in get_secret_value_response:
            return json.loads(get_secret_value_response['SecretString'])
        else:
            return json.loads(base64.b64decode(get_secret_value_response['SecretBinary']))

# Google Cloud Vision 클라이언트 초기화
vision_client = vision.ImageAnnotatorClient()

# OpenAI 클라이언트 초기화
openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

@app.post("/api/ocr")
async def process_images(files: List[UploadFile] = File(...)):
    results = []
    
    for file in files:
        # 이미지 파일 읽기
        image_content = await file.read()
        image = vision.Image(content=image_content)
        
        # OCR 수행
        response = vision_client.text_detection(image=image)
        texts = response.text_annotations
        
        if texts:
            extracted_text = texts[0].description
            
            # 개별 페이지 요약 생성
            summary_response = openai_client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[
                    {"role": "system", "content": "한국어 텍스트를 간단히 요약해주세요."},
                    {"role": "user", "content": extracted_text}
                ]
            )
            summary = summary_response.choices[0].message.content
            
            # 이미지를 base64로 변환
            img = Image.open(io.BytesIO(image_content))
            img_byte_arr = io.BytesIO()
            img.save(img_byte_arr, format=img.format)
            img_byte_arr = img_byte_arr.getvalue()
            
            results.append({
                "filename": file.filename,
                "text": extracted_text,
                "summary": summary,
                "image": img_byte_arr
            })
    
    return {"results": results}

@app.get("/api/health")
async def health_check():
    return {"status": "healthy"} 