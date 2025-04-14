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

# .env 파일에서 환경 변수 로드 
load_dotenv()

# FastAPI 애플리케이션 인스턴스 생성
app = FastAPI()
# AWS Lambda에서 실행하기 위한 핸들러 생성
handler = Mangum(app)

# CORS (Cross-Origin Resource Sharing) 미들웨어 설정
# - allow_origins: 허용할 출처 (기본값: 모든 출처)
# - allow_credentials: 쿠키 및 인증 헤더 허용
# - allow_methods: 허용할 HTTP 메서드 (모든 메서드 허용)
# - allow_headers: 허용할 HTTP 헤더 (모든 헤더 허용)
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("ALLOWED_ORIGINS", "*").split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Tesseract OCR 엔진 경로 설정
# AWS Lambda 환경에서의 Tesseract 실행 파일 경로
pytesseract.pytesseract.tesseract_cmd = '/opt/tesseract/bin/tesseract'

# OpenAI API 클라이언트 초기화
# 환경 변수에서 API 키를 가져와서 설정
openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# 이미지 OCR 처리 및 요약을 위한 엔드포인트
# POST /api/ocr
# 다중 파일 업로드 지원
@app.post("/api/ocr")
async def process_images(files: List[UploadFile] = File(...)):
    # 처리 결과를 저장할 리스트
    results = []
    
    # 업로드된 각 파일에 대해 처리
    for file in files:
        # 이미지 파일을 메모리에서 읽기
        image_content = await file.read()
        # PIL을 사용하여 이미지 객체 생성
        image = Image.open(io.BytesIO(image_content))
        
        try:
            # Tesseract OCR을 사용하여 이미지에서 텍스트 추출
            # 한국어와 영어 모두 인식하도록 설정
            extracted_text = pytesseract.image_to_string(image, lang='kor+eng')
            
            # OpenAI API를 사용하여 추출된 텍스트 요약 생성
            summary_response = openai_client.chat.completions.create(
                model="gpt-3.5-turbo",  # 사용할 모델 지정
                messages=[
                    {"role": "system", "content": "한국어 텍스트를 간단히 요약해주세요."},  # 시스템 프롬프트
                    {"role": "user", "content": extracted_text}  # 사용자 입력 (추출된 텍스트)
                ]
            )
            # 생성된 요약 텍스트 추출
            summary = summary_response.choices[0].message.content
            
            # 이미지를 base64 형식으로 변환하여 저장
            img_byte_arr = io.BytesIO()
            image.save(img_byte_arr, format=image.format or 'JPEG')
            img_byte_arr = img_byte_arr.getvalue()
            
            # 처리 결과를 리스트에 추가
            results.append({
                "filename": file.filename,  # 원본 파일명
                "text": extracted_text,     # 추출된 텍스트
                "summary": summary,         # 생성된 요약
                "image": img_byte_arr       # base64로 인코딩된 이미지
            })
        except Exception as e:
            # 오류 발생 시 오류 정보를 결과에 추가
            results.append({
                "filename": file.filename,
                "error": str(e)
            })
    
    # 모든 처리 결과 반환
    return {"results": results}

# 서버 상태 확인을 위한 헬스 체크 엔드포인트
# GET /api/health
@app.get("/api/health")
async def health_check():
    return {"status": "healthy"}  # 서버가 정상적으로 실행 중임을 나타내는 응답 