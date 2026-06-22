"""Strategy registry — loads, stores, and evaluates trading strategies."""

import importlib
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Type

import pandas as pd
import yaml

from src.strategy.base import BaseStrategy, Strategy
from src.strategy.signals import Signal

# Registry: strategy_id -> BaseStrategy class
_STRATEGY_CLASSES: Dict[str, Type[BaseStrategy]] = {}

# Loaded instances: strategy_id -> BaseStrategy
_STRATEGY_INSTANCES: Dict[str, BaseStrategy] = {}

# Strategy configs: strategy_id -> Strategy
_STRATEGY_CONFIGS: Dict[str, Strategy] = {}


def register_strategy_class(strategy_id: str, cls: Type[BaseStrategy]) -> None:
    """Register a strategy class in the global registry.

    Args:
        strategy_id: Unique identifier for the strategy.
        cls: The strategy class (must extend BaseStrategy).
    """
    _STRATEGY_CLASSES[strategy_id] = cls


def _discover_strategies() -> None:
    """Auto-discover and import all strategy modules in src/strategy/strategies/."""
    strategies_dir = Path(__file__).parent / "strategies"
    if not strategies_dir.exists():
        return

    for py_file in sorted(strategies_dir.glob("*.py")):
        if py_file.name.startswith("_"):
            continue
        module_name = f"src.strategy.strategies.{py_file.stem}"
        try:
            importlib.import_module(module_name)
        except ImportError as e:
            print(f"Warning: Could not import {module_name}: {e}")


def load_strategies(config_dir: Optional[str] = None) -> Dict[str, Strategy]:
    """Load all strategy configurations from YAML files.

    Args:
        config_dir: Path to the directory containing strategy YAML configs.
            Defaults to configs/strategies/ relative to the project root.

    Returns:
        Dictionary mapping strategy IDs to Strategy dataclass instances.
    """
    if config_dir is None:
        # Walk up from this file to find project root
        project_root = Path(__file__).parent.parent.parent
        config_dir = str(project_root / "configs" / "strategies")

    config_path = Path(config_dir)
    if not config_path.exists():
        return {}

    for yaml_file in sorted(config_path.glob("*.yaml")):
        with open(yaml_file, "r") as f:
            raw = yaml.safe_load(f)
        if not raw or "id" not in raw:
            continue

        # Convert list fields that might be strings
        for field_name in ["timeframes", "assets", "entry_rules", "exit_rules"]:
            val = raw.get(field_name, [])
            if isinstance(val, str):
                raw[field_name] = [val]

        config = Strategy(**raw)
        _STRATEGY_CONFIGS[config.id] = config

    return dict(_STRATEGY_CONFIGS)


def get_strategy(strategy_id: str) -> Optional[BaseStrategy]:
    """Get a strategy instance by ID.

    If the strategy is already instantiated, returns the cached instance.
    Otherwise, looks up the class from the registry and instantiates it.

    Args:
        strategy_id: The strategy identifier.

    Returns:
        BaseStrategy instance or None if not found.
    """
    if strategy_id in _STRATEGY_INSTANCES:
        return _STRATEGY_INSTANCES[strategy_id]

    # Load configs if not yet loaded
    if not _STRATEGY_CONFIGS:
        load_strategies()

    # Discover strategy classes if not yet discovered
    if not _STRATEGY_CLASSES:
        _discover_strategies()

    config = _STRATEGY_CONFIGS.get(strategy_id)
    cls = _STRATEGY_CLASSES.get(strategy_id)

    if cls is not None:
        instance = cls(config=config)
        _STRATEGY_INSTANCES[strategy_id] = instance
        return instance

    return None


def list_strategies(
    category: Optional[str] = None,
    asset_type: Optional[str] = None,
) -> List[Strategy]:
    """List strategy configurations, optionally filtered.

    Args:
        category: Filter by category (trend, mean_reversion, momentum, breakout, value, growth).
        asset_type: Filter by asset type (stocks, crypto, forex).

    Returns:
        List of matching Strategy dataclass instances.
    """
    if not _STRATEGY_CONFIGS:
        load_strategies()

    results = list(_STRATEGY_CONFIGS.values())

    if category:
        results = [s for s in results if s.category == category]

    if asset_type:
        results = [s for s in results if asset_type in s.assets]

    return results


def evaluate(
    strategy_id: str,
    data: pd.DataFrame,
    symbol: str = "",
) -> Signal:
    """Evaluate a strategy on market data.

    Args:
        strategy_id: ID of the strategy to evaluate.
        data: OHLCV DataFrame with datetime index.
        symbol: Asset symbol for the signal.

    Returns:
        Signal from the strategy evaluation.
    """
    strategy = get_strategy(strategy_id)
    if strategy is None:
        return Signal(
            direction=0.0,
            confidence=0.0,
            reasoning=f"Strategy '{strategy_id}' not found",
            strategy_id=strategy_id,
            symbol=symbol,
        )

    if not strategy.validate_data(data):
        return Signal(
            direction=0.0,
            confidence=0.0,
            reasoning=f"Insufficient data: need {strategy.minimum_data_points()} bars, got {len(data)}",
            strategy_id=strategy_id,
            symbol=symbol,
        )

    signal = strategy.evaluate(data)
    signal.symbol = symbol
    return signal


def add_strategy(config: Dict[str, Any]) -> Strategy:
    """Add a custom strategy from a configuration dictionary.

    Args:
        config: Dictionary with Strategy fields.

    Returns:
        The created Strategy instance.

    Raises:
        ValueError: If required fields are missing.
    """
    if "id" not in config or "name" not in config:
        raise ValueError("Config must include 'id' and 'name' fields")

    for field_name in ["timeframes", "assets", "entry_rules", "exit_rules"]:
        val = config.get(field_name, [])
        if isinstance(val, str):
            config[field_name] = [val]

    strategy = Strategy(**config)
    _STRATEGY_CONFIGS[strategy.id] = strategy
    return strategy
