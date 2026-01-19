---
description: Query or modify CSV/TSV files with automatic validation
allowed-tools: Read, Write, Edit, Bash
argument-hint: <file_path> <your request>
---

# CSV/TSV File Operations

You are helping the user work with a CSV or TSV file. The file path is: `$1`

The user's request is: $ARGUMENTS

## Instructions

1. **First, run the validator** to understand the file structure:

```bash
echo '{"tool_name": "Read", "tool_input": {"file_path": "$1"}}' | python3 hooks/validate_csv.py
```

This will provide you with:
   - File encoding (UTF-8, UTF-16, etc.)
   - Format detection (CSV vs TSV)
   - Delimiter detection
   - Row and column counts
   - Column headers
   - Data quality warnings (missing values, type inconsistencies, etc.)
   - Any structural errors

2. **Analyze the validator output** to understand:
   - The file's structure and schema
   - Any data quality issues to be aware of
   - The correct encoding and delimiter to use when processing

3. **Ask for clarification** if the user's request is ambiguous. Use the validator output to inform your questions (e.g., "I see columns X, Y, Z - which would you like to filter by?")

4. **Choose your approach** based on the task:
   - For simple operations: use Python's built-in `csv` module
   - For complex queries, aggregations, or transformations: use `pandas` if available
   - Match the file's detected encoding and delimiter when reading/writing

5. **Execute the user's request**:
   - **For queries**: Output results to the console. If the user asks, also save to a file.
   - **For modifications**: Create a NEW file by default (e.g., `original_modified.csv`). Only overwrite the original if the user explicitly requests it.
   - Preserve the original file's encoding and format unless the user requests a change.

## Important Notes

- Always read the file first to get the validator report before processing
- Handle encoding properly - the validator will tell you the detected encoding
- For TSV files, use `\t` as the delimiter
- When creating output files, use UTF-8 encoding unless preserving original encoding is important
- If the file has metadata rows (detected by validator), skip them when processing data
- Report any errors clearly and suggest fixes when possible
