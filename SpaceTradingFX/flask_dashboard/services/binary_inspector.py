"""
Space-Trade-Fx Binary Metadata & Compatibility Triage Engine (.ex4 / .ex5 Inspector)

Performs static binary analysis on compiled MetaTrader executable files (.ex4 and .ex5):
1. Header & Magic Bytes parsing (pre-Build 600 MQL4 vs. Build 600+ MQL4 vs. MQL5 64-bit).
2. Sliding-window Shannon Entropy calculation to detect DRM/Market protection or encryption.
3. Static unencrypted string extraction (ASCII & UTF-16LE) to recover input parameters,
   indicator buffer configurations, DLL imports, and symbol references.
4. Triage and recommendation generation for migration or signal bridge integration.
"""

from __future__ import annotations

import io
import logging
import math
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, BinaryIO, Union

logger = logging.getLogger("space_trading_fx.binary_inspector")


@dataclass
class SpaceTradeBinaryReport:
    """Diagnostic and compatibility triage report for a compiled MetaTrader binary."""

    filename: str
    file_size_bytes: int
    file_type: str  # "ex4" or "ex5"
    build_era: str  # "MQL4_PRE_BUILD_600", "MQL4_BUILD_600_PLUS", "MQL5"
    architecture: str  # "32-bit" or "64-bit"
    average_entropy: float
    max_chunk_entropy: float
    is_encrypted_or_packed: bool
    dll_imports: list[str] = field(default_factory=list)
    extracted_parameters: list[str] = field(default_factory=list)
    detected_buffers: list[str] = field(default_factory=list)
    detected_indicators: list[str] = field(default_factory=list)
    network_endpoints: list[str] = field(default_factory=list)
    currency_symbols: list[str] = field(default_factory=list)
    risk_level: str = "LOW"  # "LOW", "MEDIUM", "HIGH"
    recommended_strategy: str = ""
    analysis_notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class SpaceTradeBinaryInspector:
    """
    Space-Trade-Fx Static Binary Inspector for .ex4 and .ex5 files.
    """

    def __init__(self, chunk_size: int = 512, entropy_threshold: float = 7.3) -> None:
        self.chunk_size = chunk_size
        self.entropy_threshold = entropy_threshold
        self.logger = logger

    def calculate_shannon_entropy(self, data: bytes) -> float:
        """
        Calculate Shannon entropy in bits per byte: H = -sum(p * log2(p)).
        A value approaching 8.0 indicates high randomness/encryption/compression.
        """
        if not data:
            return 0.0

        byte_counts = [0] * 256
        for b in data:
            byte_counts[b] += 1

        total_bytes = len(data)
        entropy = 0.0
        for count in byte_counts:
            if count > 0:
                p = count / total_bytes
                entropy -= p * math.log2(p)

        return round(entropy, 4)

    def calculate_section_entropies(self, data: bytes) -> tuple[float, float, list[float]]:
        """
        Compute average entropy and max chunk entropy across sliding windows.
        """
        if not data:
            return 0.0, 0.0, []

        chunk_entropies = []
        for i in range(0, len(data), self.chunk_size):
            chunk = data[i : i + self.chunk_size]
            chunk_entropies.append(self.calculate_shannon_entropy(chunk))

        avg_entropy = round(sum(chunk_entropies) / len(chunk_entropies), 4)
        max_entropy = round(max(chunk_entropies), 4)
        return avg_entropy, max_entropy, chunk_entropies

    def extract_strings(self, data: bytes, min_len: int = 4) -> tuple[list[str], list[str]]:
        """
        Extract readable ASCII and UTF-16LE strings of at least min_len characters.
        """
        ascii_strings: list[str] = []
        utf16_strings: list[str] = []

        # ASCII regex: printable ASCII 0x20 to 0x7E
        ascii_matches = re.finditer(rb"[\x20-\x7e]{" + str(min_len).encode() + rb",}", data)
        for m in ascii_matches:
            try:
                s = m.group(0).decode("ascii")
                ascii_strings.append(s)
            except Exception:
                pass

        # UTF-16LE regex: pairs of (printable ASCII, 0x00)
        utf16_matches = re.finditer(rb"(?:[\x20-\x7e]\x00){" + str(min_len).encode() + rb",}", data)
        for m in utf16_matches:
            try:
                s = m.group(0).decode("utf-16le")
                utf16_strings.append(s)
            except Exception:
                pass

        return ascii_strings, utf16_strings

    def inspect_file(
        self,
        file_source: Union[str, Path, bytes, BinaryIO],
        filename: str = "",
    ) -> SpaceTradeBinaryReport:
        """
        Analyze a .ex4 or .ex5 file and produce a comprehensive compatibility report.
        """
        raw_bytes: bytes

        if isinstance(file_source, (str, Path)):
            path = Path(file_source)
            if not filename:
                filename = path.name
            raw_bytes = path.read_bytes()
        elif isinstance(file_source, bytes):
            raw_bytes = file_source
            if not filename:
                filename = "uploaded_binary.bin"
        elif isinstance(file_source, io.IOBase):
            raw_bytes = file_source.read()
            if not filename:
                filename = getattr(file_source, "name", "stream_binary.bin")
        else:
            raise TypeError("Unsupported file source type.")

        file_size = len(raw_bytes)
        filename_lower = filename.lower()

        # Determine target file type
        if filename_lower.endswith(".ex5") or b"EX5" in raw_bytes[:128]:
            file_type = "ex5"
        elif filename_lower.endswith(".ex4"):
            file_type = "ex4"
        else:
            # Guess from headers
            if len(raw_bytes) > 4 and raw_bytes[:4] in (b"\x85\x00\x00\x00", b"\x84\x00\x00\x00"):
                file_type = "ex4"
            else:
                file_type = "ex5" if b"EX5" in raw_bytes[:256] else "ex4"

        # Calculate Entropies
        avg_entropy, max_entropy, _ = self.calculate_section_entropies(raw_bytes)
        is_encrypted = max_entropy >= self.entropy_threshold or avg_entropy >= 7.2

        # Extract Strings
        ascii_strs, utf16_strs = self.extract_strings(raw_bytes)
        all_strs = list(dict.fromkeys(ascii_strs + utf16_strs))

        # Classify extracted strings
        extracted_params: set[str] = set()
        detected_buffers: set[str] = set()
        detected_indicators: set[str] = set()
        dll_imports: set[str] = set()
        network_endpoints: set[str] = set()
        currency_symbols: set[str] = set()
        notes: list[str] = []

        # Common forex currencies
        symbol_patterns = re.compile(
            r"\b(EURUSD|GBPUSD|USDJPY|USDCHF|AUDUSD|NZDUSD|USDCAD|EURGBP|EURJPY|GBPJPY|USDZAR|XAUUSD|BTCUSD)\b",
            re.IGNORECASE,
        )
        dll_pattern = re.compile(r"\b([a-zA-Z0-9_\-]+\.dll)\b", re.IGNORECASE)
        url_pattern = re.compile(r"https?://[^\s'\"\<\>]+", re.IGNORECASE)

        param_prefixes = (
            "Inp",
            "inp_",
            "input_",
            "extern",
            "Fast",
            "Slow",
            "Period",
            "Magic",
            "Lot",
            "StopLoss",
            "TakeProfit",
            "Slippage",
        )
        indicator_names = (
            "iRSI",
            "iMA",
            "iMACD",
            "iATR",
            "iBands",
            "iStochastic",
            "iCustom",
            "iCCI",
            "iWPR",
            "iEnvelopes",
        )
        buffer_hints = ("buffer", "indicator_buffers", "SetIndexBuffer", "PLOT_", "DRAW_")

        for s in all_strs:
            s_clean = s.strip()
            if not s_clean:
                continue

            # Check DLL imports
            for match in dll_pattern.finditer(s_clean):
                dll_imports.add(match.group(1).lower())

            # Check URLs
            for match in url_pattern.finditer(s_clean):
                network_endpoints.add(match.group(0))

            # Check Symbols
            for match in symbol_patterns.finditer(s_clean):
                currency_symbols.add(match.group(1).upper())

            # Check Indicator functions
            for ind in indicator_names:
                if ind.lower() in s_clean.lower():
                    detected_indicators.add(ind)

            # Check Input Parameters
            for prefix in param_prefixes:
                if s_clean.startswith(prefix) and len(s_clean) <= 40 and " " not in s_clean:
                    extracted_params.add(s_clean)

            # Check Buffer references
            for bh in buffer_hints:
                if bh.lower() in s_clean.lower() and len(s_clean) <= 40:
                    detected_buffers.add(s_clean)

        # Detect Build Era & Architecture
        if file_type == "ex5":
            build_era = "MQL5"
            architecture = "64-bit"
            notes.append("Modern MetaTrader 5 64-bit bytecode container detected.")
        else:
            architecture = "32-bit"
            # Build 600+ detection heuristic: presence of UTF-16LE strings and Unicode markers
            if len(utf16_strs) > 10 or b"Unicode" in raw_bytes or raw_bytes.find(b"\x00\x00\x02\x00") != -1:
                build_era = "MQL4_BUILD_600_PLUS"
                notes.append("MQL4 Build 600+ unified compiler bytecode format.")
            else:
                build_era = "MQL4_PRE_BUILD_600"
                notes.append("Legacy pre-Build 600 MQL4 bytecode format.")

        # Determine Risk Level
        risk_level = "LOW"
        if dll_imports:
            risk_level = "HIGH"
            notes.append(f"Security Alert: Executable references external DLLs: {', '.join(sorted(dll_imports))}")
        elif is_encrypted:
            risk_level = "MEDIUM"
            notes.append("Market DRM or Bytecode Encryption detected (high Shannon entropy).")

        # Formulate Recommended Strategy
        if file_type == "ex4":
            recommended_strategy = (
                "Direct execution in MT5 is impossible for .ex4 binaries. "
                "Recommended: If source .mq4 exists, use Space-Trade-Fx Strategy Transpilation Engine (Pipeline 1) "
                "to generate native MQL5 or Space-Trade-Fx Python. If only binary exists, use extracted parameter "
                "signatures to reconstruct strategy logic in Space-Trade-Fx."
            )
        elif is_encrypted:
            recommended_strategy = (
                "Binary protected by Market DRM / High Entropy encryption. Buffers cannot be hooked via standard AST. "
                "Recommended: Deploy Space-Trade-Fx Universal Object Scanner Signal Bridge (Pipeline 2) to intercept "
                "signals via chart graphical objects (OBJ_ARROW, OBJ_TEXT) and execute with dynamic ATR trailing stops."
            )
        else:
            recommended_strategy = (
                "Clean MQL5 binary with accessible bytecode. "
                "Recommended: Deploy Space-Trade-Fx Universal Buffer Signal Bridge (Pipeline 2) to intercept buffer "
                "streams via iCustom and CopyBuffer with bar gating and CTrade execution."
            )

        return SpaceTradeBinaryReport(
            filename=filename,
            file_size_bytes=file_size,
            file_type=file_type,
            build_era=build_era,
            architecture=architecture,
            average_entropy=avg_entropy,
            max_chunk_entropy=max_entropy,
            is_encrypted_or_packed=is_encrypted,
            dll_imports=sorted(list(dll_imports)),
            extracted_parameters=sorted(list(extracted_params)),
            detected_buffers=sorted(list(detected_buffers)),
            detected_indicators=sorted(list(detected_indicators)),
            network_endpoints=sorted(list(network_endpoints)),
            currency_symbols=sorted(list(currency_symbols)),
            risk_level=risk_level,
            recommended_strategy=recommended_strategy,
            analysis_notes=notes,
        )
