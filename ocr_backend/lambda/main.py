import os
import io
import json
import traceback
from datetime import datetime
from typing import List, Optional
from fastapi import FastAPI, UploadFile, File, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from PIL import Image
import pytesseract
import boto3
from botocore.exceptions import ClientError
import openai
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
import gc

# 환경 변수 설정
S3_BUCKET = os.getenv("S3_BUCKET", "ocr-temp-storage")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# S3 클라이언트 초기화
s3_client = boto3.client('s3')

# OpenAI 클라이언트 초기화
openai.api_key = OPENAI_API_KEY
openai.api_base = "https://api.openai.com/v1"
openai.http_client = None  # 프록시 오류 방지

# Tesseract OCR 경로 설정 (Lambda 환경)
pytesseract.pytesseract.tesseract_cmd = '/usr/bin/tesseract'

app = FastAPI()

# CORS 설정
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 로깅 헬퍼 함수
def log_info(message: str, **kwargs):
    log_data = {
        "timestamp": datetime.utcnow().isoformat(),
        "level": "INFO",
        "message": message,
        **kwargs
    }
    print(json.dumps(log_data))

def log_error(message: str, error: Exception = None, **kwargs):
    log_data = {
        "timestamp": datetime.utcnow().isoformat(),
        "level": "ERROR",
        "message": message,
        **kwargs
    }
    if error:
        log_data["error"] = str(error)
        log_data["traceback"] = traceback.format_exc()
    print(json.dumps(log_data))

# 이미지 전처리 함수
def preprocess_image(image: Image.Image) -> Image.Image:
    try:
        # 이미지 크기 최적화 (A4 크기 기준, 300dpi)
        max_size = (2480, 3508)
        if image.size[0] > max_size[0] or image.size[1] > max_size[1]:
            original_size = image.size
            image.thumbnail(max_size, Image.Resampling.LANCZOS)
            log_info("이미지 크기 조정", {
                "original_size": original_size,
                "new_size": image.size,
                "max_size": max_size
            })
        
        # 이미지를 RGB로 변환
        if image.mode not in ('L', 'RGB'):
            original_mode = image.mode
            image = image.convert('RGB')
            log_info("이미지 모드 변환", {
                "original_mode": original_mode,
                "new_mode": image.mode
            })
        
        return image
    except Exception as e:
        log_error("이미지 전처리 중 오류 발생", e)
        raise e

# OCR 수행 함수
def perform_ocr(image: Image.Image) -> str:
    try:
        log_info("Tesseract OCR 시작")
        extracted_text = pytesseract.image_to_string(image, lang='kor+eng')
        log_info("OCR 완료", {"text_length": len(extracted_text)})
        
        # OpenAI로 요약 생성
        log_info("OpenAI API 호출 시작")
        summary_response = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "한국어 텍스트를 간단히 요약해주세요."},
                {"role": "user", "content": extracted_text}
            ]
        )
        summary = summary_response.choices[0].message.content
        log_info("요약 완료", {"summary_length": len(summary)})
        
        return {
            "text": extracted_text,
            "summary": summary
        }
    except Exception as e:
        log_error("OCR 처리 실패", e)
        raise e

# S3에 이미지 업로드
def upload_to_s3(file: UploadFile, filename: str) -> str:
    try:
        # 이미지 데이터 읽기
        image_data = file.file.read()
        
        # S3에 업로드
        s3_client.put_object(
            Bucket=S3_BUCKET,
            Key=filename,
            Body=image_data,
            ContentType=file.content_type
        )
        
        # 프리사인드 URL 생성
        url = s3_client.generate_presigned_url(
            'get_object',
            Params={
                'Bucket': S3_BUCKET,
                'Key': filename
            },
            ExpiresIn=3600
        )
        
        return url
    except ClientError as e:
        log_error("S3 업로드 중 오류 발생", e)
        raise HTTPException(status_code=500, detail="이미지 업로드 중 오류가 발생했습니다.")
    finally:
        # 메모리 정리
        del image_data
        gc.collect()

# S3에서 이미지 다운로드
def download_from_s3(key: str) -> Image.Image:
    try:
        # S3에서 이미지 데이터 가져오기
        response = s3_client.get_object(
            Bucket=S3_BUCKET,
            Key=key
        )
        
        # 이미지 데이터 읽기
        image_data = response['Body'].read()
        
        # PIL 이미지로 변환
        image = Image.open(io.BytesIO(image_data))
        
        return image
    except ClientError as e:
        log_error("S3 다운로드 중 오류 발생", e)
        raise HTTPException(status_code=500, detail="이미지 다운로드 중 오류가 발생했습니다.")
    finally:
        # 메모리 정리
        del image_data
        gc.collect()

@app.post("/api/ocr")
async def process_image(file: UploadFile = File(...)):
    try:
        log_info("이미지 처리 시작", filename=file.filename)
        
        # 파일 크기 제한 (10MB)
        if file.size > 10 * 1024 * 1024:
            raise HTTPException(status_code=400, detail="파일 크기는 10MB를 초과할 수 없습니다.")
        
        # 이미지 파일인지 확인
        if not file.content_type.startswith('image/'):
            raise HTTPException(status_code=400, detail="이미지 파일만 업로드 가능합니다.")
        
        # 이미지 데이터 읽기
        image_data = await file.read()
        
        # PIL 이미지로 변환
        image = Image.open(io.BytesIO(image_data))
        
        # 이미지 전처리
        processed_image = preprocess_image(image)
        
        # OCR 처리
        result = perform_ocr(processed_image)
        
        # S3에 업로드
        filename = f"ocr_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{file.filename}"
        image_url = upload_to_s3(file, filename)
        
        # 결과에 이미지 URL 추가
        result["image_url"] = image_url
        
        log_info("이미지 처리 완료", filename=file.filename)
        
        return result
    except HTTPException:
        raise
    except Exception as e:
        log_error("이미지 처리 중 오류 발생", e)
        raise HTTPException(status_code=500, detail="이미지 처리 중 오류가 발생했습니다.")
    finally:
        # 메모리 정리
        if 'image_data' in locals():
            del image_data
        if 'image' in locals():
            del image
        if 'processed_image' in locals():
            del processed_image
        gc.collect()

@app.post("/api/generate-pdf")
async def generate_pdf(image_url: str, text: str):
    try:
        log_info("PDF 생성 시작", image_url=image_url)
        
        # S3 키 추출
        key = image_url.split('?')[0].split('/')[-1]
        
        # 이미지 다운로드
        image = download_from_s3(key)
        
        # PDF 생성
        pdf_buffer = io.BytesIO()
        c = canvas.Canvas(pdf_buffer, pagesize=letter)
        
        # 폰트 등록
        pdfmetrics.registerFont(TTFont('NanumGothic', 'fonts/NanumGothic.ttf'))
        c.setFont('NanumGothic', 12)
        
        # 이미지 추가
        c.drawImage(io.BytesIO(image.tobytes()), 100, 500, width=400, height=300)
        
        # 텍스트 추가
        c.drawString(100, 450, "OCR 결과:")
        text_object = c.beginText(100, 430)
        for line in text.split('\n'):
            text_object.textLine(line)
        c.drawText(text_object)
        
        c.save()
        
        # PDF 데이터 반환
        pdf_buffer.seek(0)
        pdf_data = pdf_buffer.getvalue()
        
        log_info("PDF 생성 완료", image_url=image_url)
        
        return {
            "pdf_data": pdf_data,
            "content_type": "application/pdf"
        }
    except Exception as e:
        log_error("PDF 생성 중 오류 발생", e)
        raise HTTPException(status_code=500, detail="PDF 생성 중 오류가 발생했습니다.")
    finally:
        # 메모리 정리
        if 'image' in locals():
            del image
        if 'pdf_buffer' in locals():
            del pdf_buffer
        if 'pdf_data' in locals():
            del pdf_data
        gc.collect()

@app.get("/api/health")
async def health_check():
    try:
        log_info("헬스 체크 시작")
        
        # S3 버킷 연결 테스트
        try:
            s3_client.head_bucket(Bucket=S3_BUCKET)
            s3_status = "connected"
        except ClientError as e:
            s3_status = f"error: {str(e)}"
        
        # OpenAI 연결 테스트
        try:
            openai.Model.list()
            openai_status = "connected"
        except Exception as e:
            openai_status = f"error: {str(e)}"
        
        log_info("헬스 체크 완료", s3_status=s3_status, openai_status=openai_status)
        
        return {
            "status": "healthy",
            "s3": {
                "bucket": S3_BUCKET,
                "status": s3_status
            },
            "openai": {
                "status": openai_status
            }
        }
    except Exception as e:
        log_error("헬스 체크 중 오류 발생", e)
        raise HTTPException(status_code=500, detail="헬스 체크 중 오류가 발생했습니다.")

def handler(event, context):
    from mangum import Mangum
    handler = Mangum(app)
    return handler(event, context)
