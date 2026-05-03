from fastapi import FastAPI

app = FastAPI()

@app.get("/")
def read_root():
    return {"message": "쿵로그 백엔드 서버가 정상적으로 작동 중입니다!"}

@app.get("/status")
def get_status():
    return {"sensor_status": "online", "active_sensors": 5}