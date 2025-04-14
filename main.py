# OCR 백엔드 서버의 핵심 기능을 구현한 메인 파일
# FastAPI를 사용하여 RESTful API를 제공하며, AWS Lambda에서 실행됩니다.

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
from fastapi.responses import StreamingResponse
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from io import BytesIO
import base64

# 환경 변수 로드 (.env 파일에서 API 키 등을 가져옴)
load_dotenv()

# FastAPI 애플리케이션 초기화
app = FastAPI()
# AWS Lambda에서 FastAPI를 실행하기 위한 핸들러
handler = Mangum(app)

# CORS 설정: 프론트엔드 도메인에서의 접근을 허용
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://main.d32popiutux8lz.amplifyapp.com"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
    max_age=86400
)

# API Gateway와 통합하기 위한 CORS 헤더 설정
@app.middleware("http")
async def add_cors_headers(request, call_next):
    response = await call_next(request)
    response.headers["Access-Control-Allow-Origin"] = "https://main.d32popiutux8lz.amplifyapp.com"
    response.headers["Access-Control-Allow-Credentials"] = "true"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization, X-Amz-Date, X-Api-Key, X-Amz-Security-Token, X-Amz-User-Agent"
    response.headers["Access-Control-Expose-Headers"] = "*"
    response.headers["Access-Control-Max-Age"] = "86400"
    return response

# Tesseract OCR 엔진 경로 설정 (AWS Lambda 환경)
pytesseract.pytesseract.tesseract_cmd = '/opt/bin/tesseract'

# OpenAI API 클라이언트 초기화
openai_client = OpenAI(
    api_key=os.getenv("OPENAI_API_KEY"),
    http_client=None  # proxies 오류를 방지하기 위해 http_client를 None으로 설정
)

# 이미지 OCR 처리 및 요약 API 엔드포인트
# 입력: 이미지 파일 목록
# 출력: 각 이미지의 텍스트 추출 결과, 요약, 원본 이미지
@app.post("/api/ocr")
async def process_images(files: List[UploadFile] = File(...)):
    results = []
    
    for file in files:
        try:
            # 파일 크기 제한 (10MB)
            if file.size > 10 * 1024 * 1024:
                results.append({
                    "filename": file.filename,
                    "error": "파일 크기가 10MB를 초과합니다."
                })
                continue

            image_content = await file.read()
            
            # 파일이 비어있는지 확인
            if not image_content:
                results.append({
                    "filename": file.filename,
                    "error": "빈 파일입니다."
                })
                continue

            # 이미지 파일 유효성 검사
            try:
                image = Image.open(io.BytesIO(image_content))
                image.verify()  # 이미지 유효성 검증
                image = Image.open(io.BytesIO(image_content))  # verify() 후에는 다시 열어야 함
            except Exception as e:
                results.append({
                    "filename": file.filename,
                    "error": f"유효하지 않은 이미지 파일입니다: {str(e)}"
                })
                continue
            
            # Tesseract OCR로 텍스트 추출
            extracted_text = pytesseract.image_to_string(image, lang='kor+eng')
            
            # OpenAI API를 사용하여 텍스트 요약
            summary_response = openai_client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[
                    {"role": "system", "content": "한국어 텍스트를 간단히 요약해주세요."},
                    {"role": "user", "content": extracted_text}
                ]
            )
            summary = summary_response.choices[0].message.content
            
            # 이미지를 바이트 배열로 변환
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

# PDF 생성 API 엔드포인트
# 입력: OCR 처리 결과
# 출력: PDF 파일 (다운로드)
@app.post("/api/generate-pdf")
async def generate_pdf(data: dict):
    buffer = BytesIO()
    p = canvas.Canvas(buffer, pagesize=letter)
    
    # 한글 폰트 등록
    pdfmetrics.registerFont(TTFont('NanumGothic', '/var/task/fonts/NanumGothic.ttf'))
    p.setFont('NanumGothic', 12)
    
    for result in data["results"]:
        # 이미지 추가
        try:
            img_data = base64.b64decode(result["image"])
            img = Image.open(BytesIO(img_data))
            img_width, img_height = img.size
            aspect = img_height / float(img_width)
            display_width = 400
            display_height = display_width * aspect
            
            p.drawImage(BytesIO(img_data), 100, 600, width=display_width, height=display_height)
        except Exception as e:
            print(f"이미지 처리 중 오류 발생: {e}")
        
        # 텍스트 추가
        p.drawString(100, 550, f"요약: {result['summary']}")
        p.drawString(100, 500, "원문:")
        
        # 긴 텍스트를 여러 줄로 나누기
        text = result["text"]
        y = 480
        for line in text.split('\n'):
            if y < 100:  # 페이지 끝에 도달하면 새 페이지 생성
                p.showPage()
                p.setFont('NanumGothic', 12)
                y = 700
            p.drawString(100, y, line)
            y -= 20
        
        p.showPage()
    
    p.save()
    buffer.seek(0)
    
    return StreamingResponse(
        buffer,
        media_type="application/pdf",
        headers={"Content-Disposition": "attachment; filename=ocr_results.pdf"}
    )

# 서버 상태 확인을 위한 헬스 체크 엔드포인트
@app.get("/api/health")
async def health_check():
    return {"status": "healthy"} 