import os
import tempfile

# before anything imports the app: a throwaway database file and the sandbox URL.
# a file and not :memory:, the connect run writes from its own thread
os.environ["DATABASE_URL"] = "sqlite:///" + os.path.join(tempfile.mkdtemp(), "test.db")
os.environ["PAYPAL_BASE_URL"] = "https://api-m.sandbox.paypal.com"
os.environ["DEMO_MODE"] = "live"
