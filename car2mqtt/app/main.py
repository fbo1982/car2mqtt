from app.api.server import create_app
import os
import uvicorn

app = create_app()

if __name__ == "__main__":
    port = int(os.getenv("APP_PORT", "8099"))
    uvicorn.run(app, host="0.0.0.0", port=port)
