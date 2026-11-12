import os
import uvicorn
from src.api.app import app

for folder in ["uploads", "static/uploads", "data", "runs"]:
    os.makedirs(folder, exist_ok=True)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=7860)
