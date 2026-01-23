# Installation

## Requirements

- **Python 3.10 or higher**
- No additional dependencies required
- **uvloop** (optional): aiocop works with both standard asyncio and uvloop out of the box

## Install from PyPI

The recommended way to install aiocop is from [PyPI](https://pypi.org/project/aiocop/):

### Using uv (recommended)

```bash
uv add aiocop
```

### Using pip

```bash
pip install aiocop
```

### Using poetry

```bash
poetry add aiocop
```

## Install from Source

For development or to get the latest changes:

### Clone and install

```bash
git clone https://github.com/Feverup/aiocop.git
cd aiocop
uv sync
```

### Install with test dependencies

```bash
uv sync --extra test
```

### Download tarball

```bash
curl -OJL https://github.com/Feverup/aiocop/tarball/master
tar -xzf aiocop-master.tar.gz
cd aiocop-master
uv pip install .
```

## Verify Installation

After installation, verify aiocop is working:

```python
import aiocop

print(f"aiocop version: {aiocop.__version__}")
print(f"Available functions: {len(aiocop.get_blocking_events_dict())} blocking events monitored")
```

## Next Steps

- [Quick Start](quickstart.md) - Get started in 5 minutes
- [User Guide](guide.md) - Learn all features
