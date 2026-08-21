"""Kronos forecasting Celery tasks."""
from backend.celery_app import celery_app


@celery_app.task(name="backend.tasks.kronos_tasks.run_kronos", bind=True, max_retries=2)
def run_kronos(self, prices: list, market_type: str = "<CRYPTO>"):
    """Run Kronos probabilistic forecast on given prices."""
    try:
        from core_engine.kronos_forecast import KronosProbabilisticModel
        model = KronosProbabilisticModel()
        return model.forecast(prices, market_type=market_type)
    except Exception as exc:
        raise self.retry(exc=exc, countdown=5)
