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
import boto3
import uuid
from datetime import datetime, timedelta

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

# S3 클라이언트 초기화
s3_client = boto3.client('s3')
S3_BUCKET = os.getenv('S3_BUCKET')

# S3에 파일 업로드 함수
async def upload_to_s3(file_bytes: bytes, file_name: str) -> str:
    # 고유한 파일 이름 생성
    ext = os.path.splitext(file_name)[1]
    unique_filename = f"{uuid.uuid4()}{ext}"
    
    try:
        # S3에 업로드
        s3_client.put_object(
            Bucket=S3_BUCKET,
            Key=unique_filename,
            Body=file_bytes,
            ContentType=f"image/{ext[1:]}"  # .jpg -> image/jpg
        )
        
        # 24시간 유효한 프리사인드 URL 생성
        url = s3_client.generate_presigned_url(
            'get_object',
            Params={
                'Bucket': S3_BUCKET,
                'Key': unique_filename
            },
            ExpiresIn=86400  # 24시간
        )
        
        return url
    except Exception as e:
        print(f"S3 업로드 중 오류 발생: {str(e)}")
        raise e

# 이미지 OCR 처리 및 요약 API 엔드포인트
# 입력: 이미지 파일 목록
# 출력: 각 이미지의 텍스트 추출 결과, 요약, 원본 이미지
@app.post("/api/ocr")
async def process_images(files: List[UploadFile] = File(...)):
    print("OCR 처리 시작")
    results = []
    
    if not files:
        print("업로드된 파일이 없음")
        return {"error": "업로드된 파일이 없습니다."}
    
    print(f"업로드된 파일 수: {len(files)}")
    
    for file in files:
        try:
            print(f"파일 처리 시작: {file.filename}")
            print(f"파일 콘텐츠 타입: {file.content_type}")
            
            # 파일 확장자 체크
            allowed_extensions = {'.jpg', '.jpeg', '.png', '.bmp', '.gif', '.tiff'}
            file_ext = os.path.splitext(file.filename)[1].lower()
            if file_ext not in allowed_extensions:
                print(f"지원하지 않는 파일 형식: {file_ext}")
                results.append({
                    "filename": file.filename,
                    "error": f"지원하지 않는 파일 형식입니다: {file_ext}"
                })
                continue
            
            # 파일 읽기
            try:
                image_content = await file.read()
                print(f"파일 크기: {len(image_content)} bytes")
                
                if len(image_content) == 0:
                    print("빈 파일")
                    results.append({
                        "filename": file.filename,
                        "error": "빈 파일입니다."
                    })
                    continue
                
                # 이미지 파일 유효성 검사
                try:
                    print("이미지 열기 시도")
                    image = Image.open(io.BytesIO(image_content))
                    
                    # 이미지 기본 정보 출력
                    print(f"이미지 포맷: {image.format}, 크기: {image.size}, 모드: {image.mode}")
                    
                    # 이미지 크기 최적화 (너무 큰 경우)
                    max_size = (800, 800)  # 최대 크기 지정
                    if image.size[0] > max_size[0] or image.size[1] > max_size[1]:
                        image.thumbnail(max_size, Image.Resampling.LANCZOS)
                        print(f"이미지 크기 조정됨: {image.size}")
                    
                    # OCR 처리를 위해 이미지를 RGB로 변환
                    if image.mode not in ('L', 'RGB'):
                        print(f"이미지 모드 변환: {image.mode} -> RGB")
                        image = image.convert('RGB')
                    
                    print("Tesseract OCR 시작")
                    extracted_text = pytesseract.image_to_string(image, lang='kor+eng')
                    print(f"추출된 텍스트 길이: {len(extracted_text)}")
                    print(f"추출된 텍스트 미리보기: {extracted_text[:100]}")
                    
                    print("OpenAI API 호출 시작")
                    summary_response = openai_client.chat.completions.create(
                        model="gpt-3.5-turbo",
                        messages=[
                            {"role": "system", "content": "한국어 텍스트를 간단히 요약해주세요."},
                            {"role": "user", "content": extracted_text}
                        ]
                    )
                    summary = summary_response.choices[0].message.content
                    print(f"요약 텍스트 길이: {len(summary)}")
                    
                    # 이미지를 S3에 업로드
                    print("S3 업로드 시작")
                    img_byte_arr = io.BytesIO()
                    image.save(img_byte_arr, format='JPEG', quality=85)
                    img_byte_arr = img_byte_arr.getvalue()
                    
                    # S3에 업로드하고 URL 받기
                    image_url = await upload_to_s3(img_byte_arr, file.filename)
                    print("S3 업로드 완료")
                    
                    results.append({
                        "filename": file.filename,
                        "text": extracted_text,
                        "summary": summary,
                        "image": image_url  # S3 URL
                    })
                    print(f"파일 처리 완료: {file.filename}")
                    
                except Exception as e:
                    print(f"이미지 처리 중 오류 발생: {str(e)}")
                    results.append({
                        "filename": file.filename,
                        "error": str(e)
                    })
            except Exception as e:
                print(f"파일 읽기 중 오류 발생: {str(e)}")
                results.append({
                    "filename": file.filename,
                    "error": str(e)
                })
        except Exception as e:
            print(f"파일 처리 중 오류 발생: {str(e)}")
            results.append({
                "filename": file.filename,
                "error": str(e)
            })
    
    print("모든 파일 처리 완료")
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
    return {"status": "healthy"} 