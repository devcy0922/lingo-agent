import os
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    PORT: int = 9095
    HOST: str = "0.0.0.0"
    
    # SQLite 기본 DB 경로 설정
    DATABASE_URL: str = "sqlite:///../data/db.sqlite3"
    
    # LLM Gateway 설정
    # 기본값은 로컬 호스트 또는 맥미니 IP로 유도
    LLM_GATEWAY_URL: str = "http://192.168.0.5:8000/v1"
    LLM_MODEL: str = "meta-llama/Meta-Llama-3-8B-Instruct"
    
    # 가상 Output 경로
    OUTPUT_DIR: str = "../data/output"

    class Config:
        # 상위 디렉토리나 현재 디렉토리의 .env 파일을 찾아서 로드
        env_file = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")
        env_file_encoding = "utf-8"

settings = Settings()

# 필요한 데이터 디렉토리 생성
os.makedirs(os.path.dirname(settings.DATABASE_URL.replace("sqlite:///", "")), exist_ok=True)
os.makedirs(settings.OUTPUT_DIR, exist_ok=True)
