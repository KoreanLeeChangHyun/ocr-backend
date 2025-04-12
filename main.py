import os
from fastapi import FastAPI, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from openai import OpenAI
from dotenv import load_dotenv
from PIL import Image
import io
from typing import List
from mangum import Mangum
import pytesseract

# 환경 변수 로드
load_dotenv()

app = FastAPI()
handler = Mangum(app)

# CORS 설정
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("ALLOWED_ORIGINS", "*").split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Tesseract 설정
pytesseract.pytesseract.tesseract_cmd = '/opt/tesseract/bin/tesseract'

# OpenAI 클라이언트 초기화
openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

@app.post("/api/ocr")
async def process_images(files: List[UploadFile] = File(...)):
    results = []
    
    for file in files:
        # 이미지 파일 읽기
        image_content = await file.read()
        image = Image.open(io.BytesIO(image_content))
        
        # OCR 수행 (한국어 설정)
        try:
            extracted_text = pytesseract.image_to_string(image, lang='kor+eng')
            
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
            img_byte_arr = io.BytesIO()
            image.save(img_byte_arr, format=image.format or 'JPEG')
            img_byte_arr = img_byte_arr.getvalue()
            
            results.append({
                "filename": file.filename,
                "text": extracted_text,
                "summary": summary,
                "image": img_byte_arr
            })
        except Exception as e:
            results.append({
                "filename": file.filename,
                "error": str(e)
            })
    
    return {"results": results}

@app.get("/api/health")
async def health_check():
    return {"status": "healthy"} 