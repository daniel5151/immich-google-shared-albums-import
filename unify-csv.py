#!/usr/bin/env python3
import os
import csv
import argparse
import shutil
from collections import defaultdict

def unify_csv_groups(folder_path):
    # Check if the folder exists
    if not os.path.isdir(folder_path):
        print(f"Error: The folder '{folder_path}' does not exist.")
        return

    print(f"Scanning '{folder_path}' for groups to unify...\n" + "-"*40)

    # Create the 'pre-unify' directory if it doesn't exist
    pre_unify_dir = os.path.join(folder_path, "pre-unify")
    os.makedirs(pre_unify_dir, exist_ok=True)

    file_groups = defaultdict(list)

    # 1. Identify and group the files
    for filename in os.listdir(folder_path):
        # Skip directories (like the pre-unify folder itself)
        if not os.path.isfile(os.path.join(folder_path, filename)):
            continue

        if not filename.lower().endswith('.csv'):
            continue

        # Skip files that have already been unified
        if filename.lower().endswith('-unified.csv'):
            continue

        # Strip '.csv' extension and split by the LAST underscore
        name_without_ext = filename[:-4]
        base_name, sep, suffix = name_without_ext.rpartition('_')

        if sep:
            file_groups[base_name].append(filename)

    # 2. Process each group
    for base_name, files in file_groups.items():
        if len(files) < 2:
            print(f"ℹ️  Skipping '{base_name}': Only 1 file found.")
            continue

        # Sort chronologically
        files.sort()

        output_filename = f"{base_name}-unified.csv"
        output_path = os.path.join(folder_path, output_filename)

        print(f"🔄 Unifying group: '{base_name}' ({len(files)} files)")

        seen_rows = set()
        header_written = False
        total_rows_written = 0

        try:
            # Open the new unified file for writing
            with open(output_path, mode='w', encoding='utf-8-sig', newline='') as outfile:
                writer = csv.writer(outfile)

                # Iterate through each file in the current group
                for filename in files:
                    file_path = os.path.join(folder_path, filename)

                    with open(file_path, mode='r', encoding='utf-8-sig') as infile:
                        reader = csv.reader(infile)

                        try:
                            header = next(reader)
                        except StopIteration:
                            continue

                        if not header_written:
                            writer.writerow(header)
                            header_written = True

                        # Write rows, ignoring duplicates
                        for row in reader:
                            row_tuple = tuple(row)
                            if row_tuple not in seen_rows:
                                writer.writerow(row)
                                seen_rows.add(row_tuple)
                                total_rows_written += 1

            print(f"  ✅ Saved: {output_filename} ({total_rows_written} unique rows)")

            # 3. Move original files to the pre-unify folder
            for filename in files:
                source_path = os.path.join(folder_path, filename)
                dest_path = os.path.join(pre_unify_dir, filename)
                shutil.move(source_path, dest_path)

            print(f"  📂 Moved {len(files)} original files to 'pre-unify/'")

        except UnicodeDecodeError:
            print(f"  ❌ Encoding error in group '{base_name}'. Ensure CSVs are UTF-8.")
        except Exception as e:
            print(f"  ❌ Error processing group '{base_name}': {e}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Unify CSVs and move originals to a pre-unify folder.")
    parser.add_argument("folder", type=str, help="Path to the folder containing your scraped CSVs.")

    args = parser.parse_args()
    unify_csv_groups(args.folder)
