FROM public.ecr.aws/lambda/python:3.9

# Tesseract OCR 설치
RUN yum install -y tesseract tesseract-langpack-kor

# 작업 디렉토리 설정
WORKDIR ${LAMBDA_TASK_ROOT}

# 필요한 파일 복사
COPY requirements.txt .
COPY main.py .
COPY fonts/ ./fonts/

# 의존성 설치
RUN pip install -r requirements.txt

# Lambda 핸들러 설정
CMD [ "main.handler" ] 