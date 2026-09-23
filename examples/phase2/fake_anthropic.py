"""A stand-in for api.anthropic.com that costs nothing.

Every call "uses" 20,000 input + 2,000 output tokens. On Claude Haiku 4.5
($1 / $5 per million) that is $0.02 + $0.01 = $0.03 per call.
"""
import json
import sys

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

USAGE = {"input_tokens": 20_000, "output_tokens": 2_000}
app = FastAPI()


def _message(model: str, usage: dict) -> dict:
    return {"id": "msg_fake", "type": "message", "role": "assistant", "model": model,
            "content": [{"type": "text", "text": "Sure, doing it again!"}],
            "stop_reason": "end_turn", "stop_sequence": None, "usage": usage}


@app.post("/v1/messages")
async def messages(request: Request):
    body = await request.json()
    model = body["model"]
    if not body.get("stream"):
        return JSONResponse(_message(model, USAGE))

    def events():
        start = _message(model, {**USAGE, "output_tokens": 1})
        start["content"], start["stop_reason"] = [], None
        yield ("message_start", {"type": "message_start", "message": start})
        yield ("content_block_start", {"type": "content_block_start", "index": 0,
                                       "content_block": {"type": "text", "text": ""}})
        yield ("content_block_delta", {"type": "content_block_delta", "index": 0,
                                       "delta": {"type": "text_delta", "text": "Sure, doing it again!"}})
        yield ("content_block_stop", {"type": "content_block_stop", "index": 0})
        yield ("message_delta", {"type": "message_delta",
                                 "delta": {"stop_reason": "end_turn", "stop_sequence": None},
                                 "usage": {"output_tokens": USAGE["output_tokens"]}})
        yield ("message_stop", {"type": "message_stop"})

    sse = (f"event: {n}\ndata: {json.dumps(d)}\n\n" for n, d in events())
    return StreamingResponse(sse, media_type="text/event-stream")


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=int(sys.argv[1]) if len(sys.argv) > 1 else 8788,
                log_level="warning")
