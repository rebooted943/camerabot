"""ArbitrageSniper - selective arbitrage scanner for used photography gear.

Modular pipeline:
    providers/   -> where we *buy* (OLX, Publi24, Vinted, Wallapop)
    benchmarks/  -> how we *value* (MPB floor price, eBay sold, F64 retail)
    arbitrage    -> the selective filter / spread calculator
    notifier     -> Telegram alerts
    database     -> SQLite de-duplication state (committed by CI)
"""

__version__ = "1.0.0"
