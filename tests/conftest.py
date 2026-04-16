import os


# Force Qt into a non-visible backend during pytest collection so UI tests do
# not create transient native windows on Windows.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
