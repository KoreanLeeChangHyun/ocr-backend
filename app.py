from fastapi import FastAPI, UploadFile, File, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from mangum import Mangum
import os
from dotenv import load_dotenv
import openai
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
from io import BytesIO
import base64
import pytesseract
from PIL import Image

# 환경 변수 로드
load_dotenv()

# OpenAI API 키 설정
openai.api_key = os.getenv("OPENAI_API_KEY")

app = FastAPI()

# CORS 미들웨어 설정
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://main.d32popiutux8lz.amplifyapp.com"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
)

@app.post("/ocr")
async def process_image(file: UploadFile = File(...)):
    try:
        # 이미지 데이터 읽기
        image_data = await file.read()
        
        # 이미지를 PIL Image로 변환
        image = Image.open(BytesIO(image_data))
        
        # Tesseract OCR 수행
        extracted_text = pytesseract.image_to_string(image, lang='kor+eng')
        
        if not extracted_text.strip():
            extracted_text = "텍스트를 찾을 수 없습니다."
        
        # OpenAI로 요약 생성
        summary = await generate_summary(extracted_text)
        
        response = JSONResponse({
            "text": extracted_text,
            "summary": summary,
            "image": base64.b64encode(image_data).decode('utf-8')
        })
        
        # CORS 헤더 추가
        response.headers["Access-Control-Allow-Origin"] = "https://main.d32popiutux8lz.amplifyapp.com"
        response.headers["Access-Control-Allow-Credentials"] = "true"
        return response
        
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"error": str(e)},
            headers={
                "Access-Control-Allow-Origin": "https://main.d32popiutux8lz.amplifyapp.com",
                "Access-Control-Allow-Credentials": "true"
            }
        )

@app.options("/ocr")
async def options_ocr():
    response = JSONResponse({})
    response.headers["Access-Control-Allow-Origin"] = "https://main.d32popiutux8lz.amplifyapp.com"
    response.headers["Access-Control-Allow-Methods"] = "POST, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "*"
    response.headers["Access-Control-Allow-Credentials"] = "true"
    return response

@app.post("/generate-pdf")
async def generate_pdf(data: dict):
    try:
        # PDF 생성
        buffer = BytesIO()
        c = canvas.Canvas(buffer, pagesize=letter)
        
        # 각 페이지의 내용을 PDF에 추가
        for page in data["results"]:
            c.setFont("Helvetica", 16)
            c.drawString(50, 750, f"페이지 {page['page']}")
            
            c.setFont("Helvetica", 12)
            c.drawString(50, 720, "요약:")
            c.setFont("Helvetica", 10)
            c.drawString(50, 700, page["summary"])
            
            c.setFont("Helvetica", 12)
            c.drawString(50, 650, "텍스트:")
            c.setFont("Helvetica", 10)
            text = page["text"]
            y = 630
            for line in text.split('\n'):
                c.drawString(50, y, line)
                y -= 15
                if y < 50:
                    c.showPage()
                    y = 750
            
            c.showPage()
        
        c.save()
        
        # PDF 데이터 반환
        buffer.seek(0)
        return {"pdf": base64.b64encode(buffer.getvalue()).decode('utf-8')}
    except Exception as e:
        return {"error": str(e)}

async def generate_summary(text: str) -> str:
    try:
        response = await openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "다음 텍스트를 간결하게 요약해주세요."},
                {"role": "user", "content": text}
            ],
            max_tokens=150
        )
        return response.choices[0].message.content
    except Exception as e:
        return f"요약 생성 중 오류 발생: {str(e)}"

# Lambda 핸들러
handler = Mangum(app) 