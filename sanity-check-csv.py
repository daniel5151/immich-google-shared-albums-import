#!/usr/bin/env python3
import os
import csv
import argparse

def check_csv_duplicates(folder_path):
    # Check if the folder exists
    if not os.path.isdir(folder_path):
        print(f"Error: The folder '{folder_path}' does not exist.")
        return

    print(f"Scanning folder: {folder_path}\n" + "-"*30)

    # Loop through all files in the directory
    for filename in os.listdir(folder_path):
        if filename.lower().endswith('.csv'):
            file_path = os.path.join(folder_path, filename)
            seen_rows = set()
            duplicate_count = 0

            try:
                # Open and read the CSV file
                with open(file_path, mode='r', encoding='utf-8-sig') as file:
                    reader = csv.reader(file)
                    for row in reader:
                        # Convert the row list to a tuple so it can be hashed in a set
                        row_tuple = tuple(row)

                        if row_tuple in seen_rows:
                            duplicate_count += 1
                        else:
                            seen_rows.add(row_tuple)

                # Report findings
                if duplicate_count > 0:
                    print(f"⚠️  {filename}: Found {duplicate_count} duplicate row(s).")
                else:
                    print(f"✅  {filename}: No duplicates found.")

            except UnicodeDecodeError:
                print(f"❌  {filename}: Encoding error. Try saving the CSV as UTF-8.")
            except Exception as e:
                print(f"❌  {filename}: Error reading file - {e}")

if __name__ == "__main__":
    # Set up argument parsing for the CLI
    parser = argparse.ArgumentParser(description="Check all CSV files in a folder for duplicate rows.")
    parser.add_argument("folder", type=str, help="The path to the folder containing your CSV files.")

    # Parse the arguments
    args = parser.parse_args()

    # Run the function with the provided folder path
    check_csv_duplicates(args.folder)
