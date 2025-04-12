# OCR 백엔드 서버

이 프로젝트는 책 페이지 이미지를 OCR 처리하고 텍스트를 요약하는 FastAPI 기반 백엔드 서버입니다.

## 주요 기능

- Tesseract OCR을 사용한 텍스트 추출
- OpenAI API를 사용한 텍스트 요약
- 다중 이미지 파일 처리
- AWS Lambda 배포 지원

## 기술 스택

- FastAPI
- Tesseract OCR
- OpenAI API
- AWS Lambda
- Mangum

## 설정 방법

1. Tesseract OCR 설치:
```bash
# Ubuntu/Debian
sudo apt-get install tesseract-ocr
sudo apt-get install tesseract-ocr-kor

# macOS
brew install tesseract
brew install tesseract-lang
```

2. 필요한 Python 패키지 설치:
```bash
pip install -r requirements.txt
```

3. 환경 변수 설정:
- `OPENAI_API_KEY`: OpenAI API 키

## 로컬 실행

```bash
uvicorn main:app --reload
```

## API 엔드포인트

- `POST /api/ocr`: 이미지 파일을 업로드하여 OCR 처리
- `GET /api/health`: 서버 상태 확인 