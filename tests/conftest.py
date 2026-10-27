import os, tempfile
os.environ["APPDATA"] = tempfile.mkdtemp(prefix="mt-test-")  # keep tests away from real tokens
