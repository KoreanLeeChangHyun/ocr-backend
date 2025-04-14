# OCR 백엔드 서버

## 개요
FastAPI와 AWS Lambda를 사용한 OCR 백엔드 서버입니다. 이미지에서 텍스트를 추출하고 OpenAI를 사용하여 요약을 생성합니다.

## 기능
- 이미지 OCR 처리
- 텍스트 요약 생성
- PDF 파일 생성
- S3를 이용한 임시 파일 저장
- RESTful API 제공

## 기술 스택
- Python 3.9
- FastAPI
- AWS Lambda
- AWS S3
- Tesseract OCR
- OpenAI API
- Serverless Framework

## AWS 리소스
- Lambda 함수
- API Gateway
- S3 버킷 (임시 파일 저장용)
  - 24시간 후 자동 삭제
  - CORS 설정
  - 프리사인드 URL 사용

## CI/CD 파이프라인

### GitHub Actions 워크플로우
`.github/workflows/deploy.yml` 파일에 정의된 CI/CD 파이프라인은 다음과 같이 동작합니다:

1. **트리거 조건**
   - `main` 브랜치에 푸시
   - 수동 트리거 (workflow_dispatch)

2. **작업 단계**
   ```yaml
   jobs:
     deploy:
       runs-on: ubuntu-latest
       steps:
         - 체크아웃
         - Python 3.9 설정
         - 의존성 설치
         - AWS 자격 증명 구성
         - 서버리스 배포
   ```

3. **환경 변수**
   - `AWS_ACCESS_KEY_ID`: AWS 액세스 키
   - `AWS_SECRET_ACCESS_KEY`: AWS 시크릿 키
   - `OPENAI_API_KEY`: OpenAI API 키

4. **배포 프로세스**
   - 서버리스 프레임워크 v3를 사용하여 배포
   - AWS Lambda 함수 생성/업데이트
   - API Gateway 엔드포인트 구성
   - S3 버킷 생성 및 설정
   - 환경 변수 설정

## 로컬 개발 환경 설정

1. Python 가상 환경 생성 및 활성화:
   ```bash
   python -m venv venv
   source venv/bin/activate  # Linux/Mac
   venv\Scripts\activate     # Windows
   ```

2. 의존성 설치:
   ```bash
   pip install -r requirements.txt
   ```

3. 환경 변수 설정:
   ```bash
   cp .env.example .env
   # .env 파일에 필요한 환경 변수 설정
   ```

4. 로컬 서버 실행:
   ```bash
   uvicorn main:app --reload
   ```

## 배포

1. GitHub Secrets 설정:
   - AWS 자격 증명
   - OpenAI API 키

2. `main` 브랜치에 푸시:
   ```bash
   git push origin main
   ```

3. 배포 상태 확인:
   - GitHub Actions 탭에서 워크플로우 실행 상태 확인
   - AWS CloudWatch에서 로그 확인
   - AWS S3에서 버킷 생성 확인

## API 엔드포인트

- `POST /api/ocr`: 이미지 OCR 처리
  - 이미지 파일을 S3에 업로드
  - OCR 처리 후 텍스트 추출
  - OpenAI로 요약 생성
  - S3 URL 반환
- `POST /api/generate-pdf`: PDF 생성
- `GET /api/health`: 서버 상태 확인

## 모니터링

- AWS CloudWatch 로그
- API Gateway 메트릭스
- Lambda 함수 메트릭스
- S3 버킷 메트릭스 