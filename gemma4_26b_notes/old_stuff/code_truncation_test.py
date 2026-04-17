import os
import sys
import time

def long_function_to_test_truncation():
    """
    This function contains many lines of comments and print statements
    to ensure that the response stream is long enough to potentially
    be truncated by the system during the generation process.
    """
    print("Starting long function...")
    for i in range(100):
        if i % 10 == 0:
            print(f"Progress: {i}%")
        time.sleep(0.01)
    print("Function complete.")

class TestClass:
    def __init__(self, name):
        self.name = name
        self.data = []

    def add_data(self, value):
        self.data.append(value)
        print(f"Added {value} to {self.name}")

    def process_data(self):
        print(f"Processing data for {self.name}...")
        for item in self.data:
            print(f"- {item}")

def main():
    print("Starting the script...")
    test_obj = TestClass("StressTest")
    
    # Adding data
    for i in range(50):
        test_obj.add_data(f"item_{i}")
    
    # Processing data
    test_obj.process_data()
    
    long_function_to_test_truncation()
    
    print("Script finished successfully!")

if __name__ == '__main__':
    main()
