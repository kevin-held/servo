def function_one():
    """
    This is a long docstring designed to test if the read operation
    or the response stream truncates multi-line strings during
    the retrieval process.
    """
    print("Function One Executed")
    return True

def function_two(data):
    """
    Testing parameter handling and multi-line strings.
    """
    for item in data:
        print(f"Processing: {item}")
    return len(data)

if __name__ == '__main__':
    test_data = [1, 2, 3, 4, 5]
    if function_one():
        result = function_two(test_data)
        print(f"Result: {result}")
