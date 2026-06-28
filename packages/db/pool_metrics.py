from prometheus_client import REGISTRY
from prometheus_client.metrics_core import GaugeMetricFamily
from sqlalchemy.ext.asyncio import AsyncEngine


class _DBPoolCollector:
    def __init__(self, engine: AsyncEngine, service: str) -> None:
        self._engine = engine
        self._service = service

    def describe(self):
        return []

    def collect(self):
        pool = self._engine.pool
        for name, help_text, value in (
            ("db_pool_checkedin", "Idle connections in pool", pool.checkedin()),
            ("db_pool_checkedout", "Connections in use", pool.checkedout()),
            ("db_pool_overflow", "Overflow connections in use", pool.overflow()),
            ("db_pool_size", "Configured pool size", pool.size()),
        ):
            g = GaugeMetricFamily(name, help_text, labels=["service"])
            g.add_metric([self._service], value)
            yield g


def register_pool_metrics(engine: AsyncEngine, service: str) -> None:
    REGISTRY.register(_DBPoolCollector(engine, service))
