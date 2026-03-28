#!/usr/bin/env python3
import sys
import csv
from pathlib import Path

# --- CONFIGURATION ---
# Add any exact column names you want to completely drop here.
COLUMNS_TO_IGNORE = {"Learn more about how storage works"}

def normalize_csv_files(input_folder_name):
    input_path = Path(input_folder_name)

    # 1. Validate Input Directory
    if not input_path.is_dir():
        print(f"Error: The directory '{input_folder_name}' does not exist.")
        sys.exit(1)

    # 2. Setup Output Directory
    output_path = input_path.parent / f"{input_path.name}-normalized"
    output_path.mkdir(parents=True, exist_ok=True)
    print(f"Output directory ready: {output_path}")

    csv_files = list(input_path.glob('*.csv'))
    if not csv_files:
        print(f"No CSV files found in '{input_folder_name}'.")
        sys.exit(0)

    # Phase 1: Determine the superset of columns
    print("\nPhase 1: Scanning files to determine the column superset...")
    master_columns = []

    for file_path in csv_files:
        with file_path.open('r', newline='', encoding='utf-8-sig') as f:
            reader = csv.reader(f)
            try:
                headers = next(reader)
                for header in headers:
                    # Skip columns we explicitly want to ignore
                    if header in COLUMNS_TO_IGNORE:
                        continue

                    # Add to superset if it's new
                    if header not in master_columns:
                        master_columns.append(header)
            except StopIteration:
                pass # Skip empty files

    print(f"Found {len(master_columns)} unique columns across all files (excluding ignored).")

    # Phase 2: Normalize and write to the new directory
    print("\nPhase 2: Normalizing files...")
    for file_path in csv_files:
        out_file_path = output_path / file_path.name

        # CRITICAL: Do not overwrite existing files
        if out_file_path.exists():
            print(f"  [SKIPPED] {file_path.name} - File already exists in output folder.")
            continue

        with file_path.open('r', newline='', encoding='utf-8-sig') as infile, \
             out_file_path.open('w', newline='', encoding='utf-8') as outfile:

            reader = csv.DictReader(infile)

            # extrasaction='ignore' is crucial here!
            # It tells the writer to quietly discard any columns in the
            # input rows that aren't in our master_columns list.
            writer = csv.DictWriter(
                outfile,
                fieldnames=master_columns,
                extrasaction='ignore'
            )

            writer.writeheader()
            for row in reader:
                writer.writerow(row)

        print(f"  [SUCCESS] Normalized: {file_path.name}")

    print("\nNormalization complete!")

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: ./normalize <input_folder_path>")
        sys.exit(1)

    normalize_csv_files(sys.argv[1])
