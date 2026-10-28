"""Single AGH stdio entry; all eight tools use the same persistent task store."""
from mcp_runtime import serve

if __name__ == '__main__':
    raise SystemExit(serve())
