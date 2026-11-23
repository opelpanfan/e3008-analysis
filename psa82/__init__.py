"""PSA 82 kWh (Peugeot e-3008 / Fiat 600e) bench worker.

Listen-only unless transmission is explicitly enabled. Diagnostic writes are
not implemented. Routine start and ClearDiagnosticInformation run only after
an operator confirmation token.
"""

__version__ = "0.1.0"
