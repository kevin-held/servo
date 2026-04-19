import mpmath
import sys

def verify():
    try:
        mpmath.mp.dps = 500
        truth = str(mpmath.mp.pi)
        with open('workspace/gemma4_26b/pi_result_1.txt', 'r') as f:
            candidate = f.read().strip()
        
        mismatch = False
        for i, (c, t) in enumerate(zip(candidate, truth)):
            if c != t:
                print(f'Mismatch at index {i}: expected "{t}", found "{c}"')
                mismatch = True
                break
        
        if not mismatch:
            if len(candidate) < len(truth):
                print('Candidate is a valid prefix of the truth string, but ends early.')
            else:
                print('Candidate is a perfect match for the truth string (up to 500 dps).')
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    verify()