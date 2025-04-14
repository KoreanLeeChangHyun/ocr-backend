# OCR 백엔드 서버의 핵심 기능을 구현한 메인 파일
# FastAPI를 사용하여 RESTful API를 제공하며, AWS Lambda에서 실행됩니다.

import os
from fastapi import FastAPI, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from openai import OpenAI
from dotenv import load_dotenv
from PIL import Image
import io
from typing import List, Dict, Any
from mangum import Mangum
import pytesseract
from fastapi.responses import StreamingResponse
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from io import BytesIO
import base64
import boto3
import uuid
from datetime import datetime, timedelta
import json
import traceback

# 환경 변수 로드 (.env 파일에서 API 키 등을 가져옴) TEST
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

# 로깅 헬퍼 함수
def log_info(message: str, **kwargs):
    timestamp = datetime.now().isoformat()
    log_data = {
        "timestamp": timestamp,
        "level": "INFO",
        "message": message
    }
    if kwargs:
        log_data.update(kwargs)
    print(json.dumps(log_data, ensure_ascii=False))

def log_error(message: str, error: Exception = None, **kwargs):
    timestamp = datetime.now().isoformat()
    log_data = {
        "timestamp": timestamp,
        "level": "ERROR",
        "message": message
    }
    if error:
        log_data["error_type"] = type(error).__name__
        log_data["error_message"] = str(error)
        log_data["stacktrace"] = traceback.format_exc()
    if kwargs:
        log_data.update(kwargs)
    print(json.dumps(log_data, ensure_ascii=False))

# S3 클라이언트 초기화
log_info("S3 클라이언트 초기화")
s3_client = boto3.client('s3')
S3_BUCKET = os.getenv('S3_BUCKET')
log_info(f"S3 버킷 설정", {"bucket": S3_BUCKET})

# S3에 파일 업로드 함수
async def upload_to_s3(file_bytes: bytes, file_name: str) -> str:
    try:
        # 고유한 파일 이름 생성
        ext = os.path.splitext(file_name)[1]
        unique_filename = f"{uuid.uuid4()}{ext}"
        log_info(f"S3 업로드 시작", {
            "original_filename": file_name,
            "unique_filename": unique_filename,
            "file_size": len(file_bytes),
            "bucket": S3_BUCKET
        })
        
        # S3에 업로드
        s3_client.put_object(
            Bucket=S3_BUCKET,
            Key=unique_filename,
            Body=file_bytes,
            ContentType=f"image/{ext[1:]}"
        )
        log_info("S3 업로드 완료", {"filename": unique_filename})
        
        # 24시간 유효한 프리사인드 URL 생성
        url = s3_client.generate_presigned_url(
            'get_object',
            Params={
                'Bucket': S3_BUCKET,
                'Key': unique_filename
            },
            ExpiresIn=86400
        )
        log_info("프리사인드 URL 생성 완료", {"url_expiry": "24시간"})
        
        return url
    except Exception as e:
        log_error("S3 업로드 실패", e, {
            "filename": file_name,
            "bucket": S3_BUCKET
        })
        raise e

# 이미지 OCR 처리 및 요약 API 엔드포인트
# 입력: 이미지 파일 목록
# 출력: 각 이미지의 텍스트 추출 결과, 요약, 원본 이미지
@app.post("/api/ocr")
async def process_images(files: List[UploadFile] = File(...)):
    log_info("OCR 처리 시작")
    results = []
    
    if not files:
        log_info("업로드된 파일 없음")
        return {"error": "업로드된 파일이 없습니다."}
    
    log_info(f"파일 처리 시작", {"file_count": len(files)})
    
    for file in files:
        try:
            log_info(f"파일 처리", filename=file.filename, content_type=file.content_type)
            
            # 파일 크기 제한 (10MB)
            if file.size > 10 * 1024 * 1024:
                raise ValueError("파일 크기가 10MB를 초과합니다")
            
            # 파일 내용 읽기
            image_content = file.file.read()
            log_info(f"파일 읽기 완료", filename=file.filename, size=len(image_content))
            
            # 이미지 데이터 검증
            if not image_content:
                raise ValueError("파일 내용이 비어있습니다")
            
            # 이미지 형식 검증
            try:
                image = Image.open(io.BytesIO(image_content))
                image.verify()  # 이미지 데이터 검증
                image = Image.open(io.BytesIO(image_content))  # 검증 후 다시 열기
            except Exception as e:
                log_error(f"이미지 검증 실패", error_type=type(e).__name__, error_message=str(e), filename=file.filename)
                raise ValueError(f"유효하지 않은 이미지 파일입니다: {str(e)}")
            
            # 이미지 처리
            log_info(f"이미지 처리 시작", filename=file.filename)
            processed_image = preprocess_image(image)
            
            # OCR 처리
            log_info(f"OCR 처리 시작", filename=file.filename)
            ocr_text = perform_ocr(processed_image)
            
            # 결과 저장
            results.append({
                "filename": file.filename,
                "text": ocr_text,
                "size": len(image_content),
                "content_type": file.content_type
            })
            log_info(f"파일 처리 완료", filename=file.filename)
            
        except Exception as e:
            log_error(f"파일 처리 중 오류", error_type=type(e).__name__, error_message=str(e), filename=file.filename)
            results.append({
                "filename": file.filename,
                "error": str(e),
                "status": "error"
            })
    
    log_info(f"모든 파일 처리 완료", total_files=len(files), success_count=len([r for r in results if "error" not in r]))
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
            # S3 URL에서 이미지 다운로드
            response = s3_client.get_object(
                Bucket=S3_BUCKET,
                Key=result["image"].split('/')[-1].split('?')[0]
            )
            img_data = response['Body'].read()
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
    try:
        log_info("헬스 체크 시작", {"bucket": S3_BUCKET})
        
        # S3 버킷 존재 여부 확인
        s3_client.head_bucket(Bucket=S3_BUCKET)
        log_info("S3 버킷 연결 확인 완료")
        
        return {
            "status": "healthy",
            "s3_status": "connected",
            "bucket": S3_BUCKET
        }
    except Exception as e:
        log_error("헬스 체크 실패", e, {"bucket": S3_BUCKET})
        return {
            "status": "unhealthy",
            "s3_status": "error",
            "error": str(e),
            "bucket": S3_BUCKET
        } 