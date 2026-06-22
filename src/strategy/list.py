"""CLI entry point for listing strategies: python -m src.strategy.list"""

from src.strategy.library import list_strategies, load_strategies


def main() -> None:
    """Print all loaded strategies in a formatted table."""
    load_strategies()
    strategies = list_strategies()

    print(f"\n{'='*80}")
    print(f"  Trading Intelligence — Strategy Library ({len(strategies)} strategies)")
    print(f"{'='*80}")
    print(
        f"{'ID':<25} {'Name':<30} {'Category':<18} {'Assets'}"
    )
    print(f"{'-'*80}")

    for s in strategies:
        assets = ", ".join(s.assets) if s.assets else "—"
        print(f"{s.id:<25} {s.name:<30} {s.category:<18} {assets}")

    print(f"{'='*80}\n")


if __name__ == "__main__":
    main()
