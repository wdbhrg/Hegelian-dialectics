from __future__ import annotations

from typing import Dict, Optional

from fastapi import FastAPI
from pydantic import BaseModel, Field

from quality_pipeline import run_quality_pipeline
from retrieval_eval import run_offline_retrieval_eval


class AnalyzeRequest(BaseModel):
    question: str = Field(min_length=1, description="User question")
    model_hint: Optional[str] = Field(default="", description="Optional model hint for cache key")


class AnalyzeResponse(BaseModel):
    result: Dict[str, object]


app = FastAPI(title="Hegel Logic Quality API", version="1.0.0")


@app.get("/health")
def health() -> Dict[str, object]:
    return {"ok": True, "service": "hegel-quality-api"}


@app.post("/analyze", response_model=AnalyzeResponse)
def analyze(req: AnalyzeRequest) -> AnalyzeResponse:
    out = run_quality_pipeline(req.question.strip(), model_hint=(req.model_hint or "").strip())
    return AnalyzeResponse(result=out)


@app.get("/quality/retrieval-eval")
def retrieval_eval() -> Dict[str, object]:
    return run_offline_retrieval_eval(top_k=6)

