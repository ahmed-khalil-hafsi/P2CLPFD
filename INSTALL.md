# Installation

## Prerequisites

P2CLPFD requires **SWI-Prolog** (v9.0 or later) installed on your system.

### macOS

```bash
brew install swi-prolog
```

### Ubuntu / Debian

```bash
sudo apt install swi-prolog
```

### Conda (cross-platform)

```bash
conda install -c conda-forge swi-prolog
```

### Verify

```bash
swipl --version
# SWI-Prolog version 9.2.8 for arm64-darwin
```

## Option A: Python package

```bash
pip install p2clpfd
```

### Verify

```python
from p2clpfd import Solver

s = Solver()
s.load_csv("sample.csv")
result = s.solve()
print(f"TCO: {result['tco']}")
```

> **Note:** If `pip install p2clpfd` fails during `janus-swi` build, ensure
> SWI-Prolog is installed and `pkg-config` can find it:
> ```bash
> pkg-config --modversion libswipl   # should print a version number
> ```
> On macOS with Homebrew, you may need to set environment variables:
> ```bash
> export SWI_HOME_DIR="$(brew --prefix swi-prolog)/lib/swipl"
> export SWI_LIB_DIR="$(brew --prefix swi-prolog)/lib/swipl/lib/$(swipl --arch)"
> pip install p2clpfd
> ```

## Option B: Command line (no Python)

```bash
git clone https://github.com/ahmed-khalil-hafsi/P2CLPFD.git
cd P2CLPFD
swipl -q -g run -g halt main.pl
```

### Load your own data

Edit `facts.pl` or prepare a CSV:

```bash
swipl -q -g "load_and_run('my_data.csv')" -g halt main.pl
```

## Option C: HTTP server

```bash
swipl -g "['main.pl','json_api.pl'], server(8080), thread_get_message(_)" &
```

```bash
curl -s -X POST localhost:8080/solve \
  -H "Content-Type: application/json" \
  -d '{"csv_path":"sample.csv"}'
```

See [TECHNICAL.md](TECHNICAL.md) for full API reference.
