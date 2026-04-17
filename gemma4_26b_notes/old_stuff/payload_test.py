import json

def generate_large_payload(size):
    """Generates a large dictionary to test for truncation."""
    data = {}
    for i in range(size):
        data[f"key_{i}"] = "a" * 100
    return data

if __name__ == "__main__":
    # Generating a payload of roughly 50KB
    large_data = generate_large_payload(500)
    print(json.dumps(large_data))
