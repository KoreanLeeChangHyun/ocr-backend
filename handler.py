from mangum import Mangum
from app import app

# Lambda 핸들러
handler = Mangum(app) 