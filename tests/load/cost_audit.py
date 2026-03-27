
def audit_logging_savings(raw_log_bytes, filtered_log_bytes):
    savings = (1 - (filtered_log_bytes / raw_log_bytes)) * 100
    print(f"Raw Logs: {raw_log_bytes/1024/1024:.2f} MB")
    print(f"Filtered Logs: {filtered_log_bytes/1024/1024:.2f} MB")
    print(f"Projected Savings: {savings:.2f}%")
    return savings

# Mock audit result for 24h simulation
if __name__ == "__main__":
    raw = 100 * 1024 * 1024 * 1024 # 100 GB
    filtered = 6.4 * 1024 * 1024 * 1024 # 6.4 GB
    savings = audit_logging_savings(raw, filtered)
    assert savings >= 93, "Cost savings target not met!"
