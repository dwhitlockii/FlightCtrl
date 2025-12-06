from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI()


class ChatRequest(BaseModel):
    model: str
    messages: list


@app.post("/api/chat")
def chat(_: ChatRequest):
    return {"message": {"content": "[mock ollama response]"}} 
