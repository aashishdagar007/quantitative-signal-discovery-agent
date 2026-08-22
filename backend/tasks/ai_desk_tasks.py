"""AI Desk Celery tasks — runs LangGraph multi-agent pipeline asynchronously."""
from backend.celery_app import celery_app


@celery_app.task(name="backend.tasks.ai_desk_tasks.run_ai_desk", bind=True, max_retries=2)
def run_ai_desk(self, symbol: str, prices: list = None):
    """Run the full LangGraph AI Desk pipeline for a given symbol."""
    import asyncio
    try:
        from core_engine.ai_desk import run_ai_desk as _run
        result = asyncio.get_event_loop().run_until_complete(
            _run(symbol=symbol, prices=prices)
        )
        return result
    except Exception as exc:
        raise self.retry(exc=exc, countdown=5)
