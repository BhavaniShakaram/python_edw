import sqlite3
import pandas as pd

# ============================================================
# SETUP: Create source and target databases (simulating IEHP)
# In real life: source = operational DB, target = EDW
# ============================================================
print("SETUP: Creating source and target databases")
print("=" * 60)

# Source DB — what we started with
source_conn = sqlite3.connect("source_claims.db")
source_conn.execute("DROP TABLE IF EXISTS claims")
source_conn.execute("""
    CREATE TABLE claims (
        claim_id INTEGER,
        member_id INTEGER,
        claim_amount REAL,
        service_date TEXT
    )
""")
source_data = [
    (1001, 12345, 500.00, '2025-01-15'),
    (1002, 12345, 300.00, '2025-01-20'),
    (1003, 12346, 750.00, '2025-02-01'),
    (1004, 12347, 200.00, '2025-02-05'),
    (1005, 12348, 1000.00, '2025-02-10'),
]
source_conn.executemany("INSERT INTO claims VALUES (?, ?, ?, ?)", source_data)
source_conn.commit()
print(f"Source has {len(source_data)} claims")

# Target DB (EDW) — simulating an ETL load with intentional bugs
target_conn = sqlite3.connect("edw_claims.db")
target_conn.execute("DROP TABLE IF EXISTS edw_claims")
target_conn.execute("""
    CREATE TABLE edw_claims (
        claim_id INTEGER,
        member_id INTEGER,
        claim_amount REAL,
        service_date TEXT
    )
""")
# Simulating ETL bugs:
# - claim 1004 didn't load (missing row)
# - claim 1003 has wrong amount (corruption: 750 → 700)
# - claim 1005 has NULL member_id (data quality issue)
# - claim 1001 got loaded twice (duplicate)
target_data = [
    (1001, 12345, 500.00, '2025-01-15'),
    (1001, 12345, 500.00, '2025-01-15'),    # duplicate
    (1002, 12345, 300.00, '2025-01-20'),
    (1003, 12346, 700.00, '2025-02-01'),    # value corruption
    (1005, None,  1000.00, '2025-02-10'),   # NULL member_id
    # claim 1004 missing entirely
]
target_conn.executemany("INSERT INTO edw_claims VALUES (?, ?, ?, ?)", target_data)
target_conn.commit()
print(f"Target has {len(target_data)} rows (with intentional bugs to find)")


# ============================================================
# STEP 1: Pull both source and target into pandas DataFrames
# ============================================================
print("\nSTEP 1: Loading data into DataFrames")
print("=" * 60)

source_df = pd.read_sql("SELECT * FROM claims", source_conn)
target_df = pd.read_sql("SELECT * FROM edw_claims", target_conn)

print("Source DataFrame:")
print(source_df)
print("\nTarget DataFrame:")
print(target_df)


# ============================================================
# CHECK 1: Row count match
# ============================================================
print("\nCHECK 1: Row count comparison")
print("=" * 60)

source_count = len(source_df)
target_count = len(target_df)

print(f"Source rows: {source_count}")
print(f"Target rows: {target_count}")

if source_count == target_count:
    print("PASS: Row counts match")
else:
    print(f"FAIL: Row count mismatch — difference of {target_count - source_count}")


# ============================================================
# CHECK 2: Find rows in source missing from target
# ============================================================
print("\nCHECK 2: Find rows in source missing from target")
print("=" * 60)

# Merge with indicator tells us where each row came from
merged = source_df.merge(
    target_df,
    on="claim_id",
    how="left",
    indicator=True,
    suffixes=("_src", "_tgt")
)
missing_in_target = merged[merged["_merge"] == "left_only"]

if len(missing_in_target) == 0:
    print("PASS: All source rows present in target")
else:
    print(f"FAIL: {len(missing_in_target)} rows missing from target:")
    print(missing_in_target[["claim_id", "member_id_src", "claim_amount_src"]])


# ============================================================
# CHECK 3: NULL checks on critical fields
# ============================================================
print("\nCHECK 3: NULL checks on critical fields in target")
print("=" * 60)

null_counts = target_df.isnull().sum()
print("NULL counts per column:")
print(null_counts)

critical_fields = ["claim_id", "member_id", "claim_amount"]
nulls_found = False
for field in critical_fields:
    n = target_df[field].isnull().sum()
    if n > 0:
        print(f"FAIL: '{field}' has {n} NULL value(s) — must not be NULL")
        nulls_found = True

if not nulls_found:
    print("PASS: No NULLs in critical fields")


# ============================================================
# CHECK 4: Duplicate detection in target
# ============================================================
print("\nCHECK 4: Duplicate detection in target")
print("=" * 60)

duplicates = target_df[target_df.duplicated(subset=["claim_id"], keep=False)]

if len(duplicates) == 0:
    print("PASS: No duplicate claim_ids")
else:
    print(f"FAIL: Found {len(duplicates)} duplicate rows:")
    print(duplicates)


# ============================================================
# CHECK 5: Value comparison — same claim_id, different values
# ============================================================
print("\nCHECK 5: Field-level value comparison")
print("=" * 60)

# Inner join — only claims that exist in both
matched = source_df.merge(target_df, on="claim_id", suffixes=("_src", "_tgt"))

# Find rows where claim_amount differs
mismatched = matched[matched["claim_amount_src"] != matched["claim_amount_tgt"]]

if len(mismatched) == 0:
    print("PASS: All matched values are identical")
else:
    print(f"FAIL: {len(mismatched)} rows have value mismatches:")
    print(mismatched[["claim_id", "claim_amount_src", "claim_amount_tgt"]])


# ============================================================
# WRAP UP
# ============================================================
source_conn.close()
target_conn.close()

print("\n" + "=" * 60)
print("VALIDATION COMPLETE")
print("=" * 60)