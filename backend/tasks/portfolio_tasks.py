"""Portfolio allocation Celery tasks."""
from backend.celery_app import celery_app


@celery_app.task(name="backend.tasks.portfolio_tasks.run_portfolio", bind=True, max_retries=2)
def run_portfolio(self, returns_dict: dict, symbols: list):
    """Run HRP + CVaR portfolio allocation."""
    import numpy as np
    try:
        from core_engine.portfolio_allocation import HierarchicalRiskParity
        returns = np.array(list(returns_dict.values())).T
        hrp = HierarchicalRiskParity()
        hrp.fit(returns, asset_symbols=symbols)
        positions = hrp.allocate()
        return {sym: {"weight": pos.weight, "asset_class": pos.asset_class}
                for sym, pos in positions.items()}
    except Exception as exc:
        raise self.retry(exc=exc, countdown=5)
