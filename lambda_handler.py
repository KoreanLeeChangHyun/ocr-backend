from fastapi import FastAPI, UploadFile, File
from mangum import Mangum
from typing import List
import os
from google.cloud import vision
import openai
from dotenv import load_dotenv

load_dotenv()

app = FastAPI()
handler = Mangum(app)

# Google Cloud Vision 클라이언트 초기화
vision_client = vision.ImageAnnotatorClient()

# OpenAI API 키 설정
openai.api_key = os.getenv("OPENAI_API_KEY")

@app.post("/ocr")
async def process_images(files: List[UploadFile] = File(...)):
    results = []
    
    for file in files:
        # 이미지 파일 읽기
        content = await file.read()
        
        # Google Cloud Vision API로 OCR 수행
        image = vision.Image(content=content)
        response = vision_client.text_detection(image=image)
        texts = response.text_annotations
        
        if texts:
            extracted_text = texts[0].description
            
            # OpenAI API로 텍스트 요약
            summary_response = openai.ChatCompletion.create(
                model="gpt-3.5-turbo",
                messages=[
                    {"role": "system", "content": "책의 페이지 내용을 간단히 요약해주세요."},
                    {"role": "user", "content": extracted_text}
                ]
            )
            summary = summary_response.choices[0].message.content
            
            results.append({
                "filename": file.filename,
                "text": extracted_text,
                "summary": summary
            })
    
    return {"results": results}

@app.get("/health")
def health_check():
    return {"status": "healthy"} 