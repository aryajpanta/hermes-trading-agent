"""Broker module — thin facade for FastAPI dependency injection."""
from src.broker.alpaca import BrokerConnection

__all__ = ["BrokerConnection"]
