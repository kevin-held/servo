import os
import json
import re

def diag():
    manifest_path = os.path.join(os.getcwd(), "codex", "manifest.json")
    persona_path = os.path.join(os.getcwd(), "codex", "manifests", "persona_core.md")
    
    print(f"Checking Manifest: {manifest_path}")
    if os.path.exists(manifest_path):
        with open(manifest_path, "r", encoding="utf-8") as f:
            content = f.read()
            print(f"Manifest content type: {type(content)}")
            print(f"Manifest content start: {repr(content[:20])}")
            try:
                data = json.loads(content)
                print("JSON parse: SUCCESS")
            except Exception as e:
                print(f"JSON parse: FAILED: {e}")
                
    print(f"\nChecking Persona: {persona_path}")
    if os.path.exists(persona_path):
        with open(persona_path, "r", encoding="utf-8") as f:
            raw = f.read()
            print(f"Persona content type: {type(raw)}")
            try:
                rendered = re.sub(r"<!--.*?-->", "", raw, flags=re.DOTALL)
                print("Regex sub: SUCCESS")
            except Exception as e:
                print(f"Regex sub: FAILED: {e}")

if __name__ == "__main__":
    diag()
