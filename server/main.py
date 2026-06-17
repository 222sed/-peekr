from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import analyzer
import state

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
    img_bytes = await file.read()
    result = analyzer.analyze(img_bytes)
    print(f"[frame] state={result['state']}  motion={result.get('motion')}  compact={result.get('compactness')}")
    return result


@app.get("/api/status")
def get_status():
    return state.get_state()


@app.get("/api/health")
def health():
    return {"ok": True}
