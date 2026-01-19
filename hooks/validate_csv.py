#!/usr/bin/env python3
"""
PostToolUse hook to exhaustively validate CSV files.

This hook runs after Write or Edit tool calls that target CSV files,
checking for all potential issues and reporting them comprehensively.
"""

import csv
import json
import os
import re
import sys
from collections import Counter
from io import StringIO
from typing import Any


class CSVValidator:
    """Exhaustive CSV file validator that collects all errors."""

    def __init__(self, file_path: str):
        self.file_path = file_path
        self.errors: list[dict[str, Any]] = []
        self.warnings: list[dict[str, Any]] = []
        self.raw_content: str = ""
        self.lines: list[str] = []
        self.rows: list[list[str]] = []
        self.headers: list[str] = []
        self.detected_dialect: csv.Dialect | None = None
        self.detected_encoding: str = ""
        self.is_tsv: bool = False
        self.metadata_rows_detected: bool = False
        self.metadata_row_count: int = 0

    def add_error(self, category: str, message: str, line: int | None = None, column: int | None = None, **extra):
        """Add an error to the collection."""
        error = {"category": category, "message": message, **extra}
        if line is not None:
            error["line"] = line
        if column is not None:
            error["column"] = column
        self.errors.append(error)

    def add_warning(self, category: str, message: str, line: int | None = None, column: int | None = None, **extra):
        """Add a warning to the collection."""
        warning = {"category": category, "message": message, **extra}
        if line is not None:
            warning["line"] = line
        if column is not None:
            warning["column"] = column
        self.warnings.append(warning)

    def validate(self) -> dict[str, Any]:
        """Run all validation checks and return results."""
        # Check file existence
        if not self.check_file_exists():
            return self.get_results()

        # Read file content
        if not self.read_file():
            return self.get_results()

        # Run all checks
        self.check_encoding_issues()
        self.check_bom()
        self.check_line_endings()
        self.check_empty_file()
        self.detect_dialect()
        self.parse_csv()
        self.check_header_issues()
        self.check_column_consistency()
        self.check_empty_rows()
        self.check_whitespace_issues()
        self.check_quoting_issues()
        self.check_data_type_consistency()
        self.check_missing_values()
        self.check_duplicate_rows()
        self.check_special_characters()
        self.check_field_length()

        return self.get_results()

    def check_file_exists(self) -> bool:
        """Check if file exists and is readable."""
        if not os.path.exists(self.file_path):
            self.add_error("file", f"File does not exist: {self.file_path}")
            return False
        if not os.path.isfile(self.file_path):
            self.add_error("file", f"Path is not a file: {self.file_path}")
            return False
        if not os.access(self.file_path, os.R_OK):
            self.add_error("file", f"File is not readable: {self.file_path}")
            return False
        return True

    def read_file(self) -> bool:
        """Read file content with encoding detection, including UTF-16."""
        # First, read raw bytes to detect encoding
        try:
            with open(self.file_path, "rb") as f:
                raw_bytes = f.read(4096)  # Read first 4KB for detection
        except Exception as e:
            self.add_error("file", f"Error reading file: {e}")
            return False

        # Detect encoding from BOM or byte patterns
        detected = self._detect_encoding_from_bytes(raw_bytes)

        if detected:
            # Try detected encoding first
            encodings = [detected]
        else:
            encodings = []

        # Add fallback encodings
        encodings.extend(["utf-8", "utf-8-sig", "latin-1", "cp1252", "iso-8859-1"])

        for encoding in encodings:
            try:
                with open(self.file_path, "r", encoding=encoding, newline="") as f:
                    self.raw_content = f.read()
                    self.detected_encoding = encoding

                    # Report non-UTF-8 encodings
                    if encoding not in ("utf-8", "utf-8-sig"):
                        if encoding.startswith("utf-16"):
                            self.add_warning(
                                "encoding",
                                f"File is {encoding.upper()} encoded",
                                suggestion="Consider converting to UTF-8 for better compatibility",
                            )
                        else:
                            self.add_warning(
                                "encoding",
                                f"File not in UTF-8 encoding, detected: {encoding}",
                                suggestion="Consider converting to UTF-8 for better compatibility",
                            )

                    self.lines = self.raw_content.splitlines(keepends=True)
                    return True
            except UnicodeDecodeError:
                continue
            except Exception as e:
                self.add_error("file", f"Error reading file with {encoding}: {e}")
                continue

        self.add_error("encoding", "Could not decode file with any common encoding")
        return False

    def _detect_encoding_from_bytes(self, raw_bytes: bytes) -> str | None:
        """Detect encoding from BOM or byte patterns."""
        # Check for BOM (Byte Order Mark)
        if raw_bytes.startswith(b"\xff\xfe\x00\x00"):
            return "utf-32-le"
        if raw_bytes.startswith(b"\x00\x00\xfe\xff"):
            return "utf-32-be"
        if raw_bytes.startswith(b"\xff\xfe"):
            return "utf-16-le"
        if raw_bytes.startswith(b"\xfe\xff"):
            return "utf-16-be"
        if raw_bytes.startswith(b"\xef\xbb\xbf"):
            return "utf-8-sig"

        # Check for UTF-16 without BOM by looking for null byte patterns
        # UTF-16-LE: ASCII chars appear as char + \x00
        # UTF-16-BE: ASCII chars appear as \x00 + char
        if len(raw_bytes) >= 4:
            # Count null bytes in even vs odd positions
            even_nulls = sum(1 for i in range(0, min(len(raw_bytes), 1000), 2) if raw_bytes[i:i+1] == b"\x00")
            odd_nulls = sum(1 for i in range(1, min(len(raw_bytes), 1000), 2) if raw_bytes[i:i+1] == b"\x00")

            sample_size = min(len(raw_bytes), 1000) // 2

            # If ~50% of positions are null bytes, it's likely UTF-16
            if sample_size > 0:
                even_ratio = even_nulls / sample_size
                odd_ratio = odd_nulls / sample_size

                # UTF-16-LE has nulls in odd positions (after each ASCII byte)
                if odd_ratio > 0.4 and even_ratio < 0.1:
                    return "utf-16-le"
                # UTF-16-BE has nulls in even positions (before each ASCII byte)
                if even_ratio > 0.4 and odd_ratio < 0.1:
                    return "utf-16-be"

        return None

    def check_encoding_issues(self):
        """Check for encoding-related issues."""
        # Check for null bytes (but not if we correctly decoded as UTF-16, since that's handled)
        if "\x00" in self.raw_content:
            # If we detected UTF-16 properly, there shouldn't be null bytes in the decoded content
            # Null bytes in decoded content indicate encoding mismatch
            if not self.detected_encoding.startswith("utf-16"):
                positions = [i for i, c in enumerate(self.raw_content) if c == "\x00"]
                self.add_error(
                    "encoding",
                    f"File contains null bytes at positions: {positions[:10]}{'...' if len(positions) > 10 else ''}",
                    count=len(positions),
                    suggestion="This may indicate UTF-16 encoding read as single-byte encoding",
                )

        # Check for common encoding errors (replacement characters)
        if "\ufffd" in self.raw_content:
            count = self.raw_content.count("\ufffd")
            self.add_error("encoding", f"File contains {count} replacement characters (encoding errors)")

    def check_bom(self):
        """Check for Byte Order Mark."""
        if self.raw_content.startswith("\ufeff"):
            self.add_warning("encoding", "File contains UTF-8 BOM (Byte Order Mark)", line=1)

    def check_line_endings(self):
        """Check for inconsistent line endings."""
        crlf_count = self.raw_content.count("\r\n")
        lf_only_count = self.raw_content.count("\n") - crlf_count
        cr_only_count = self.raw_content.count("\r") - crlf_count

        endings = []
        if crlf_count > 0:
            endings.append(f"CRLF ({crlf_count})")
        if lf_only_count > 0:
            endings.append(f"LF ({lf_only_count})")
        if cr_only_count > 0:
            endings.append(f"CR ({cr_only_count})")

        if len(endings) > 1:
            self.add_warning("format", f"Inconsistent line endings detected: {', '.join(endings)}")

    def check_empty_file(self):
        """Check if file is empty or whitespace-only."""
        if not self.raw_content.strip():
            self.add_error("content", "File is empty or contains only whitespace")

    def detect_dialect(self):
        """Detect CSV dialect (delimiter, quoting, etc.) with TSV support."""
        sample = self.raw_content[:8192]  # Use first 8KB for detection

        # First, try to detect delimiter by counting occurrences
        delimiter = self._detect_delimiter(sample)

        if delimiter:
            # Create a custom dialect
            class DetectedDialect(csv.excel):
                pass
            DetectedDialect.delimiter = delimiter

            if delimiter == "\t":
                self.is_tsv = True
                self.add_warning(
                    "format",
                    "Detected tab-separated values (TSV) format",
                    suggestion="File extension is .csv but content is tab-delimited",
                )

            self.detected_dialect = DetectedDialect
            return

        # Fall back to csv.Sniffer
        try:
            self.detected_dialect = csv.Sniffer().sniff(sample)
            if self.detected_dialect.delimiter == "\t":
                self.is_tsv = True
                self.add_warning(
                    "format",
                    "Detected tab-separated values (TSV) format",
                    suggestion="File extension is .csv but content is tab-delimited",
                )
        except csv.Error:
            # Final fallback to comma-separated
            self.add_warning("format", "Could not auto-detect CSV dialect, assuming comma-separated")
            self.detected_dialect = csv.excel

    def _detect_delimiter(self, sample: str) -> str | None:
        """Detect the most likely delimiter by analyzing the sample."""
        # Common delimiters to check
        delimiters = [",", "\t", ";", "|"]

        # Get lines for analysis - use more lines and try to find the data section
        all_lines = sample.split("\n")

        # Strategy 1: Find lines that look like data rows (have consistent delimiters)
        # Skip lines that appear to be metadata (short lines, lines without delimiters)
        candidate_lines = []
        for line in all_lines:
            stripped = line.strip()
            if not stripped:
                continue
            # A data line typically has at least one delimiter
            has_delimiter = any(d in stripped for d in delimiters)
            if has_delimiter:
                candidate_lines.append(stripped)
            if len(candidate_lines) >= 30:
                break

        if len(candidate_lines) < 2:
            # Fall back to all non-empty lines
            candidate_lines = [line.strip() for line in all_lines if line.strip()][:30]

        if len(candidate_lines) < 2:
            return None

        best_delimiter = None
        best_score = -1

        for delim in delimiters:
            # Count occurrences per line
            counts = [line.count(delim) for line in candidate_lines]

            if not counts or all(c == 0 for c in counts):
                continue

            # Filter out lines with zero count (might be metadata rows)
            non_zero_counts = [c for c in counts if c > 0]
            if len(non_zero_counts) < 2:
                continue

            # Check for consistency among lines that have this delimiter
            if len(set(non_zero_counts)) == 1 and non_zero_counts[0] > 0:
                # Perfect consistency - strong signal
                score = non_zero_counts[0] * 100 * (len(non_zero_counts) / len(counts))
            else:
                # Calculate consistency score
                avg_count = sum(non_zero_counts) / len(non_zero_counts)
                if avg_count == 0:
                    continue

                # Variance-based scoring (lower variance = better)
                variance = sum((c - avg_count) ** 2 for c in non_zero_counts) / len(non_zero_counts)
                consistency = 1 / (1 + variance)

                # Factor in how many lines have this delimiter
                coverage = len(non_zero_counts) / len(counts)
                score = avg_count * consistency * coverage * 10

            # Bonus for tab if there are many tabs (TSV indicator)
            if delim == "\t":
                avg = sum(non_zero_counts) / len(non_zero_counts) if non_zero_counts else 0
                if avg >= 3:  # Multiple tabs per line is strong TSV signal
                    score *= 2.0

            if score > best_score:
                best_score = score
                best_delimiter = delim

        # Only return if we have reasonable confidence
        if best_score > 1:
            return best_delimiter
        return None

    def parse_csv(self):
        """Parse CSV content and collect parsing errors."""
        try:
            reader = csv.reader(StringIO(self.raw_content), dialect=self.detected_dialect)
            for line_num, row in enumerate(reader, start=1):
                self.rows.append(row)
                if line_num == 1:
                    self.headers = row
        except csv.Error as e:
            self.add_error("parsing", f"CSV parsing error: {e}")

    def check_header_issues(self):
        """Check for header-related issues."""
        if not self.headers:
            self.add_error("header", "No headers found (file may be empty)")
            return

        # Check for empty headers
        empty_cols = [i + 1 for i, h in enumerate(self.headers) if not h.strip()]
        if empty_cols:
            self.add_error("header", f"Empty header(s) in column(s): {empty_cols}", line=1)

        # Check for duplicate headers
        header_counts = Counter(self.headers)
        duplicates = {h: c for h, c in header_counts.items() if c > 1 and h.strip()}
        if duplicates:
            self.add_error("header", f"Duplicate headers found: {duplicates}", line=1)

        # Check for headers with only whitespace differences
        normalized = {}
        for i, h in enumerate(self.headers):
            norm = h.strip().lower()
            if norm in normalized:
                self.add_warning(
                    "header",
                    f"Headers '{self.headers[normalized[norm]]}' (col {normalized[norm]+1}) and '{h}' (col {i+1}) differ only by whitespace/case",
                    line=1,
                )
            else:
                normalized[norm] = i

        # Check for reserved/problematic header names
        problematic = []
        for i, h in enumerate(self.headers):
            if h.lower() in ["id", "null", "none", "undefined", "nan"]:
                problematic.append((i + 1, h))
        if problematic:
            self.add_warning("header", f"Potentially problematic header names: {problematic}", line=1)

    def check_column_consistency(self):
        """Check for inconsistent number of columns."""
        if not self.rows:
            return

        # Count columns per row
        col_counts = [len(row) for row in self.rows]

        # Find the most common column count (likely the actual data structure)
        count_freq = Counter(col_counts)
        most_common_count, most_common_freq = count_freq.most_common(1)[0]

        # Determine expected columns
        # If header row count differs from most common, likely has metadata prefix
        header_cols = len(self.headers) if self.headers else len(self.rows[0])

        if most_common_freq > len(self.rows) * 0.5 and most_common_count != header_cols:
            # Most rows have a different column count than the first row
            # This suggests metadata rows at the start
            expected_cols = most_common_count
            self.metadata_rows_detected = True

            # Find where metadata ends (first row with expected column count)
            metadata_end = 0
            for i, row in enumerate(self.rows):
                if len(row) == expected_cols:
                    metadata_end = i
                    break

            if metadata_end > 0:
                self.metadata_row_count = metadata_end
                self.add_warning(
                    "structure",
                    f"File appears to have {metadata_end} metadata row(s) before tabular data",
                    suggestion=f"Data rows have {expected_cols} columns; first {metadata_end} row(s) are likely headers/metadata",
                    metadata_rows=metadata_end,
                )
                # Update headers to be the actual header row
                if metadata_end < len(self.rows):
                    self.headers = self.rows[metadata_end]
        else:
            expected_cols = header_cols
            self.metadata_rows_detected = False
            self.metadata_row_count = 0

        # Now check for truly inconsistent rows (excluding identified metadata rows)
        inconsistent = []

        for line_num, row in enumerate(self.rows, start=1):
            row_idx = line_num - 1
            # Skip metadata rows in error reporting if we detected them
            if self.metadata_rows_detected and row_idx < self.metadata_row_count:
                continue
            if len(row) != expected_cols:
                inconsistent.append({"line": line_num, "expected": expected_cols, "found": len(row)})

        if inconsistent:
            # Group by column count for cleaner reporting
            by_count = {}
            for item in inconsistent:
                count = item["found"]
                if count not in by_count:
                    by_count[count] = []
                by_count[count].append(item["line"])

            for count, lines in by_count.items():
                lines_str = str(lines[:20]) + ("..." if len(lines) > 20 else "")
                self.add_error(
                    "structure",
                    f"Rows with {count} columns (expected {expected_cols}): lines {lines_str}",
                    count=len(lines),
                )

    def check_empty_rows(self):
        """Check for empty or whitespace-only rows."""
        empty_lines = []
        for line_num, row in enumerate(self.rows, start=1):
            if not any(cell.strip() for cell in row):
                empty_lines.append(line_num)

        if empty_lines:
            lines_str = str(empty_lines[:20]) + ("..." if len(empty_lines) > 20 else "")
            self.add_warning("content", f"Empty rows found at lines: {lines_str}", count=len(empty_lines))

    def check_whitespace_issues(self):
        """Check for leading/trailing whitespace in cells."""
        leading_issues = []
        trailing_issues = []

        for line_num, row in enumerate(self.rows, start=1):
            for col_num, cell in enumerate(row, start=1):
                if cell != cell.lstrip():
                    leading_issues.append((line_num, col_num))
                if cell != cell.rstrip():
                    trailing_issues.append((line_num, col_num))

        if leading_issues:
            sample = leading_issues[:10]
            self.add_warning(
                "whitespace",
                f"Cells with leading whitespace: {len(leading_issues)} occurrences (e.g., {sample})",
                count=len(leading_issues),
            )

        if trailing_issues:
            sample = trailing_issues[:10]
            self.add_warning(
                "whitespace",
                f"Cells with trailing whitespace: {len(trailing_issues)} occurrences (e.g., {sample})",
                count=len(trailing_issues),
            )

    def check_quoting_issues(self):
        """Check for potential quoting issues in raw content."""
        # Check for unbalanced quotes
        for line_num, line in enumerate(self.lines, start=1):
            quote_count = line.count('"')
            if quote_count % 2 != 0:
                # Could be legitimate if quotes are escaped, but worth flagging
                self.add_warning("quoting", f"Odd number of quotes ({quote_count})", line=line_num)

        # Check for improperly escaped quotes
        # Pattern: quote not preceded by another quote and not at field boundary
        for line_num, line in enumerate(self.lines, start=1):
            # Look for quotes that might not be properly escaped
            if '""' not in line and '"' in line:
                # Check if quotes appear mid-field (rough heuristic)
                parts = line.split(",")
                for part in parts:
                    stripped = part.strip()
                    if '"' in stripped and not (stripped.startswith('"') and stripped.endswith('"')):
                        self.add_warning(
                            "quoting", "Potential unescaped quote in field", line=line_num, field_sample=stripped[:50]
                        )
                        break

    def check_data_type_consistency(self):
        """Check for data type consistency within columns."""
        if len(self.rows) < 2:
            return

        data_rows = self.rows[1:]  # Exclude header
        num_cols = len(self.headers) if self.headers else (len(self.rows[0]) if self.rows else 0)

        for col_idx in range(num_cols):
            col_name = self.headers[col_idx] if col_idx < len(self.headers) else f"Column {col_idx + 1}"
            types_found = {"numeric": [], "date": [], "boolean": [], "empty": [], "text": []}

            for line_num, row in enumerate(data_rows, start=2):
                if col_idx >= len(row):
                    continue

                cell = row[col_idx].strip()

                if not cell:
                    types_found["empty"].append(line_num)
                elif self._is_numeric(cell):
                    types_found["numeric"].append(line_num)
                elif self._is_date(cell):
                    types_found["date"].append(line_num)
                elif self._is_boolean(cell):
                    types_found["boolean"].append(line_num)
                else:
                    types_found["text"].append(line_num)

            # Check for mixed types (excluding empty)
            non_empty_types = {k: v for k, v in types_found.items() if v and k != "empty"}
            if len(non_empty_types) > 1:
                type_summary = {k: len(v) for k, v in non_empty_types.items()}
                self.add_warning(
                    "data_type", f"Mixed data types in column '{col_name}': {type_summary}", column=col_idx + 1
                )

    def _is_numeric(self, value: str) -> bool:
        """Check if value is numeric."""
        try:
            float(value.replace(",", ""))
            return True
        except ValueError:
            return False

    def _is_date(self, value: str) -> bool:
        """Check if value looks like a date."""
        date_patterns = [
            r"^\d{4}-\d{2}-\d{2}$",  # ISO format
            r"^\d{2}/\d{2}/\d{4}$",  # US format
            r"^\d{2}-\d{2}-\d{4}$",  # EU format
            r"^\d{4}/\d{2}/\d{2}$",  # Alternative ISO
            r"^\d{1,2}/\d{1,2}/\d{2,4}$",  # Flexible
        ]
        return any(re.match(p, value) for p in date_patterns)

    def _is_boolean(self, value: str) -> bool:
        """Check if value is boolean-like."""
        return value.lower() in ["true", "false", "yes", "no", "1", "0", "y", "n", "t", "f"]

    def check_missing_values(self):
        """Check for missing/null values and their representations."""
        null_representations = {"", "null", "NULL", "None", "none", "NA", "N/A", "n/a", "#N/A", "NaN", "nan", "-", "--"}

        missing_by_col = {}
        if len(self.rows) < 2:
            return

        num_cols = len(self.headers) if self.headers else (len(self.rows[0]) if self.rows else 0)

        for col_idx in range(num_cols):
            col_name = self.headers[col_idx] if col_idx < len(self.headers) else f"Column {col_idx + 1}"
            missing_count = 0
            representations_used = set()

            for row in self.rows[1:]:  # Skip header
                if col_idx >= len(row):
                    missing_count += 1
                    continue

                cell = row[col_idx].strip()
                if cell in null_representations:
                    missing_count += 1
                    representations_used.add(cell if cell else "(empty)")

            if missing_count > 0:
                missing_by_col[col_name] = {"count": missing_count, "representations": list(representations_used)}

        if missing_by_col:
            # Check for inconsistent null representations across the file
            all_representations = set()
            for info in missing_by_col.values():
                all_representations.update(info["representations"])

            if len(all_representations) > 1:
                self.add_warning(
                    "missing_values",
                    f"Inconsistent null value representations used: {all_representations}",
                    columns=list(missing_by_col.keys()),
                )

            # Report columns with high missing rate
            total_data_rows = len(self.rows) - 1
            for col_name, info in missing_by_col.items():
                if total_data_rows > 0:
                    missing_rate = info["count"] / total_data_rows
                    if missing_rate > 0.5:
                        self.add_warning(
                            "missing_values",
                            f"Column '{col_name}' has {missing_rate:.1%} missing values ({info['count']}/{total_data_rows})",
                        )

    def check_duplicate_rows(self):
        """Check for duplicate rows."""
        if len(self.rows) < 2:
            return

        row_tuples = [tuple(row) for row in self.rows[1:]]  # Exclude header
        row_counts = Counter(row_tuples)
        duplicates = {row: count for row, count in row_counts.items() if count > 1}

        if duplicates:
            total_dups = sum(count - 1 for count in duplicates.values())
            self.add_warning(
                "duplicates", f"Found {total_dups} duplicate rows ({len(duplicates)} unique patterns repeated)"
            )

    def check_special_characters(self):
        """Check for potentially problematic special characters."""
        problematic_chars = {
            "\r": "carriage return (not in line ending)",
            "\x0b": "vertical tab",
            "\x0c": "form feed",
            "\xa0": "non-breaking space",
            "\u2028": "line separator",
            "\u2029": "paragraph separator",
        }

        # Only flag tabs as problematic if this is NOT a TSV file
        # (tabs inside cells of a TSV would still be problematic, but we handle that separately)
        if not self.is_tsv:
            problematic_chars["\t"] = "tab (consider using TSV format)"

        found_issues = []
        for line_num, row in enumerate(self.rows, start=1):
            for col_num, cell in enumerate(row, start=1):
                for char, name in problematic_chars.items():
                    if char in cell:
                        found_issues.append((line_num, col_num, name))

        # For TSV files, check for embedded tabs within cells (which would break parsing)
        if self.is_tsv:
            # The CSV parser should have already split on tabs, so tabs in cells
            # would indicate an issue. But since we've already parsed, cells shouldn't
            # contain the delimiter. Only flag if we detect embedded tabs.
            pass

        if found_issues:
            summary = {}
            for line, col, name in found_issues:
                if name not in summary:
                    summary[name] = []
                summary[name].append((line, col))

            for name, locations in summary.items():
                sample = locations[:5]
                self.add_warning(
                    "special_chars",
                    f"Found '{name}' in {len(locations)} cells (e.g., {sample})",
                    count=len(locations),
                )

    def check_field_length(self):
        """Check for unusually long fields that might indicate issues."""
        max_reasonable_length = 10000
        long_fields = []

        for line_num, row in enumerate(self.rows, start=1):
            for col_num, cell in enumerate(row, start=1):
                if len(cell) > max_reasonable_length:
                    long_fields.append((line_num, col_num, len(cell)))

        if long_fields:
            self.add_warning(
                "field_length",
                f"Found {len(long_fields)} fields exceeding {max_reasonable_length} characters",
                fields=long_fields[:10],
            )

    def get_results(self) -> dict[str, Any]:
        """Get validation results."""
        delimiter_name = "tab" if self.is_tsv else (
            self.detected_dialect.delimiter if self.detected_dialect else "unknown"
        )
        if delimiter_name == ",":
            delimiter_name = "comma"
        elif delimiter_name == ";":
            delimiter_name = "semicolon"
        elif delimiter_name == "|":
            delimiter_name = "pipe"

        return {
            "file": self.file_path,
            "valid": len(self.errors) == 0,
            "error_count": len(self.errors),
            "warning_count": len(self.warnings),
            "errors": self.errors,
            "warnings": self.warnings,
            "stats": {
                "total_rows": len(self.rows),
                "total_columns": len(self.headers) if self.headers else 0,
                "headers": self.headers[:50] if self.headers else [],  # Truncate for display
                "encoding": self.detected_encoding,
                "delimiter": delimiter_name,
                "format": "TSV" if self.is_tsv else "CSV",
            },
        }


def format_results(results: dict[str, Any], always_show: bool = False) -> str:
    """Format validation results for display."""
    lines = []

    if results["valid"] and results["warning_count"] == 0 and not always_show:
        return ""  # No issues, return empty (hook passes silently)

    lines.append(f"\n{'='*60}")
    lines.append(f"CSV VALIDATION REPORT: {results['file']}")
    lines.append(f"{'='*60}")

    if results["stats"]["total_rows"] > 0:
        stats = results["stats"]
        info_parts = [f"Rows: {stats['total_rows']}", f"Columns: {stats['total_columns']}"]
        if stats.get("encoding"):
            info_parts.append(f"Encoding: {stats['encoding']}")
        if stats.get("format"):
            info_parts.append(f"Format: {stats['format']}")
        if stats.get("delimiter"):
            info_parts.append(f"Delimiter: {stats['delimiter']}")
        lines.append(", ".join(info_parts))

    if results["errors"]:
        lines.append(f"\n{'─'*40}")
        lines.append(f"ERRORS ({results['error_count']}):")
        lines.append(f"{'─'*40}")
        for error in results["errors"]:
            loc = ""
            if "line" in error:
                loc = f" [line {error['line']}"
                if "column" in error:
                    loc += f", col {error['column']}"
                loc += "]"
            lines.append(f"  ✗ [{error['category']}]{loc}: {error['message']}")

    if results["warnings"]:
        lines.append(f"\n{'─'*40}")
        lines.append(f"WARNINGS ({results['warning_count']}):")
        lines.append(f"{'─'*40}")
        for warning in results["warnings"]:
            loc = ""
            if "line" in warning:
                loc = f" [line {warning['line']}"
                if "column" in warning:
                    loc += f", col {warning['column']}"
                loc += "]"
            lines.append(f"  ⚠ [{warning['category']}]{loc}: {warning['message']}")
            if "suggestion" in warning:
                lines.append(f"    → {warning['suggestion']}")

    # Show headers if available and this is a "show info" context
    if always_show and results["stats"].get("headers"):
        lines.append(f"\n{'─'*40}")
        lines.append("COLUMNS:")
        lines.append(f"{'─'*40}")
        headers = results["stats"]["headers"]
        for i, header in enumerate(headers, 1):
            lines.append(f"  {i:3}. {header}")
        if results["stats"]["total_columns"] > 50:  # Truncated
            lines.append(f"  ... ({results['stats']['total_columns'] - 50} more columns)")

    lines.append(f"\n{'='*60}")
    if results["errors"]:
        status = "INVALID"
    elif results["warning_count"] > 0:
        status = "VALID (with warnings)"
    else:
        status = "VALID"
    lines.append(f"Status: {status}")
    lines.append(f"{'='*60}\n")

    return "\n".join(lines)


def main():
    """Main entry point for PostToolUse hook."""
    # Read hook input from stdin
    try:
        hook_input = json.load(sys.stdin)
    except json.JSONDecodeError:
        # Not valid JSON input, exit silently
        sys.exit(0)

    tool_name = hook_input.get("tool_name", "")
    tool_input = hook_input.get("tool_input", {})

    # Only process Read, Write and Edit tools
    if tool_name not in ["Read", "Write", "Edit"]:
        sys.exit(0)

    # Get the file path (same parameter name for all three tools)
    file_path = tool_input.get("file_path", "")

    # Only process CSV and TSV files
    lower_path = file_path.lower()
    if not (lower_path.endswith(".csv") or lower_path.endswith(".tsv")):
        sys.exit(0)

    # Validate the CSV/TSV file
    validator = CSVValidator(file_path)
    results = validator.validate()

    # Format and output results
    # For Read operations, always show the report (even if valid) to give context
    if tool_name == "Read":
        output = format_results(results, always_show=True)
    else:
        output = format_results(results)

    if output:
        print(output, file=sys.stderr)

    # Exit with error code if there are errors (not warnings)
    # For Read operations, don't block on errors - just report
    if results["errors"] and tool_name != "Read":
        sys.exit(1)
    else:
        sys.exit(0)


if __name__ == "__main__":
    main()
