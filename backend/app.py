"""FastAPI application for the standalone futures scalp analyzer."""

from __future__ import annotations

from fastapi import Depends, FastAPI

from futures_scalp_analyzer.models import FuturesScalpAnalysisResponse, FuturesScalpIdeaRequest
from futures_scalp_analyzer.price_feed import PriceFeed, SchwabQuotePriceFeed
from futures_scalp_analyzer.service import analyze_request


def create_app(price_feed: PriceFeed | None = None) -> FastAPI:
    app = FastAPI(title="Futures Scalp Analyzer", version="0.1.0")
    app.state.price_feed = price_feed or SchwabQuotePriceFeed()

    def get_price_feed() -> PriceFeed:
        return app.state.price_feed

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/futures/analyze", response_model=FuturesScalpAnalysisResponse)
    async def analyze(
        request: FuturesScalpIdeaRequest,
        feed: PriceFeed = Depends(get_price_feed),
    ) -> FuturesScalpAnalysisResponse:
        return await analyze_request(request, feed)

    @app.post("/futures/position", response_model=FuturesScalpAnalysisResponse)
    async def position(
        request: FuturesScalpIdeaRequest,
        feed: PriceFeed = Depends(get_price_feed),
    ) -> FuturesScalpAnalysisResponse:
        position_request = request.model_copy(update={"mode": "position_mgmt"})
        return await analyze_request(position_request, feed)

    return app


app = create_app()
