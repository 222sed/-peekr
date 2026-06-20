from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
import analyzer
import state
import time
import json

app = FastAPI(title="Peekr Server")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.post("/api/frame")
async def receive_frame(file: UploadFile = File(...)):
    if not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="Expected an image file")
    state.update_frame_time()
    img_bytes = await file.read()
    result = analyzer.analyze(img_bytes)
    print(f"[frame] state={result['state']}  motion={result.get('motion')}  compact={result.get('compactness')}")
    return result


@app.get("/api/status")
def get_status():
    return state.get_state()


@app.get("/api/stream")
def stream_status():
    last_state = None

    def generate():
        nonlocal last_state
        while True:
            current = state.get_state()
            if current != last_state:
                last_state = current.copy()
                yield f"data: {json.dumps(current)}\n\n"
            time.sleep(1)

    return StreamingResponse(generate(), media_type="text/event-stream")
