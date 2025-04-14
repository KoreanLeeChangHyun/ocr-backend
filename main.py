# 필요한 라이브러리 임포트
import os  # 운영체제 관련 기능 사용
from fastapi import FastAPI, UploadFile, File  # FastAPI 웹 프레임워크 및 파일 업로드 관련 기능
from fastapi.middleware.cors import CORSMiddleware  # CORS 미들웨어 (크로스 오리진 리소스 공유)
from openai import OpenAI  # OpenAI API 클라이언트
from dotenv import load_dotenv  # 환경 변수 로드
from PIL import Image  # 이미지 처리 라이브러리
import io  # 입출력 스트림 처리
from typing import List  # 타입 힌팅을 위한 List 타입
from mangum import Mangum  # AWS Lambda에서 FastAPI 실행을 위한 어댑터
import pytesseract  # OCR (광학 문자 인식) 라이브러리
from fastapi.responses import StreamingResponse
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
from io import BytesIO
import base64

# .env 파일에서 환경 변수 로드 
load_dotenv()

# FastAPI 애플리케이션 인스턴스 생성
app = FastAPI()
# AWS Lambda에서 실행하기 위한 핸들러 생성
handler = Mangum(app)

# CORS (Cross-Origin Resource Sharing) 미들웨어 설정
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://main.d32popiutux8lz.amplifyapp.com", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# API Gateway와 통합하기 위한 설정
@app.middleware("http")
async def add_cors_headers(request, call_next):
    response = await call_next(request)
    response.headers["Access-Control-Allow-Origin"] = "https://main.d32popiutux8lz.amplifyapp.com"
    response.headers["Access-Control-Allow-Credentials"] = "true"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
    return response

# Tesseract OCR 엔진 경로 설정
# AWS Lambda 환경에서의 Tesseract 실행 파일 경로
pytesseract.pytesseract.tesseract_cmd = '/opt/bin/tesseract'

# OpenAI API 클라이언트 초기화
openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# 이미지 OCR 처리 및 요약을 위한 엔드포인트
@app.post("/api/ocr")
async def process_images(files: List[UploadFile] = File(...)):
    results = []
    
    for file in files:
        image_content = await file.read()
        image = Image.open(io.BytesIO(image_content))
        
        try:
            extracted_text = pytesseract.image_to_string(image, lang='kor+eng')
            
            summary_response = openai_client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[
                    {"role": "system", "content": "한국어 텍스트를 간단히 요약해주세요."},
                    {"role": "user", "content": extracted_text}
                ]
            )
            summary = summary_response.choices[0].message.content
            
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

@app.post("/api/generate-pdf")
async def generate_pdf(data: dict):
    buffer = BytesIO()
    p = canvas.Canvas(buffer, pagesize=letter)
    
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