# AGENTS.md - Agent Coding Guidelines

This file provides guidelines for agents operating in the nl2sql_v3 repository.

## Project Overview

nl2sql_v3 is a multi-agent SQL generation system built with LangGraph. It converts natural language questions into SQL queries using LLM-powered agents. The project requires Python 3.12+ and uses `uv` for package management.

## Virtual Environment

- **Windows**: Use `.venv-win` virtual environment
- **WSL/Linux**: Use `.venv-wsl` virtual environment
- Install dependencies: `uv pip install -e ".[dev]"`

## Build/Lint/Test Commands

### Running Tests

```bash
# Run all tests
uv run pytest

# Run all unit tests
uv run pytest tests/unit/ -v

# Run all tests in a specific directory
uv run pytest src/tests/unit/nl2sql_father/ -v

# Run a single test file
uv run pytest tests/unit/metaweave/test_profiler.py -v

# Run a single test function
uv run pytest tests/unit/metaweave/test_profiler.py::test_profiler_generates_column_and_table_profiles -v

# Run tests by marker
uv run pytest -m unit -v        # unit tests only
uv run pytest -m integration -v # integration tests only
uv run pytest -m slow -v        # slow tests only

# Run with coverage
uv run pytest --cov=src --cov-report=html --cov-report=term
```

### Code Formatting and Linting

```bash
# Format code with Black
uv run black src/ tests/

# Check formatting without applying
uv run black --check src/ tests/

# Lint with Ruff
uv run ruff check src/ tests/

# Auto-fix linting issues
uv run ruff check --fix src/ tests/

# Run both (recommended)
uv run black src/ tests/ && uv run ruff check src/ tests/
```

### Type Checking

```bash
# Run mypy (if installed)
uv run mypy src/
```

## Code Style Guidelines

### General Principles

- Write clean, readable, and maintainable code
- Use type hints for all function signatures and class attributes
- Add docstrings to all public functions and classes (Chinese or English)
- Keep functions focused and single-purpose

### Naming Conventions

- **Modules/Files**: `snake_case.py` (e.g., `table_schema_loader.py`)
- **Classes**: `PascalCase` (e.g., `MetadataProfiler`, `ColumnInfo`)
- **Functions/Variables**: `snake_case` (e.g., `get_column_statistics`, `table_name`)
- **Constants**: `UPPER_SNAKE_CASE` (e.g., `DEFAULT_TIMEOUT`, `MAX_RETRIES`)
- **Private methods/attributes**: `_leading_underscore` (e.g., `_build_metadata`)

### Imports

- Use absolute imports from `src` package root
- Group imports in this order: standard library, third-party, local application
- Sort imports alphabetically within each group

```python
# Correct
import logging
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd
import yaml

from src.metaweave.core.metadata.models import ColumnInfo, TableMetadata
from src.metaweave.utils.data_utils import get_column_statistics
```

### Type Annotations

Use full type annotations for function signatures:

```python
# Good
def profile(metadata: TableMetadata, df: pd.DataFrame) -> ProfilingResult:
    ...

# Good - using modern Python 3.12+ syntax where appropriate
def process(items: list[str]) -> dict[str, int]: ...
```

### Data Classes

Use `@dataclass` for simple data containers:

```python
from dataclasses import dataclass, field
from typing import Optional

@dataclass
class ColumnInfo:
    column_name: str
    ordinal_position: int
    data_type: str
    is_nullable: bool = True
    comment: str = ""
```

### Error Handling

- Use specific exception types
- Provide meaningful error messages
- Log errors with appropriate context

```python
# Good
if not config_file.exists():
    raise FileNotFoundError(f"配置文件不存在: {config_path}")

# Good - using custom exceptions
class MetadataGenerationError(Exception):
    """元数据生成失败"""
    pass
```

### Logging

Use the project's logging utilities:

```python
from src.metaweave.utils.logger import get_metaweave_logger

logger = get_metaweave_logger("metadata")
logger.info("开始生成元数据")
logger.debug(f"Processing table: {table_name}")
```

### Testing

- Place tests in `tests/unit/` for unit tests
- Use `test_*.py` file naming convention
- Use `test_*` function naming convention
- Test one thing per test function
- Use descriptive test names

```python
def test_profiler_generates_column_and_table_profiles():
    """测试profiler生成列和表画像"""
    metadata = _build_metadata()
    df = pd.DataFrame({...})
    
    profiler = MetadataProfiler()
    result = profiler.profile(metadata, df)
    
    assert "store_id" in result.column_profiles
```

### Project Structure

```
src/
├── metaweave/           # Metadata generation module
│   ├── core/           # Core functionality
│   │   ├── metadata/  # Metadata models and generation
│   │   ├── relationships/  # Relationship detection
│   │   ├── dim_value/ # Dimension value loading
│   │   └── loaders/   # Data loaders
│   ├── services/      # External services (vector DB, LLM)
│   ├── utils/         # Utilities
│   └── cli/           # Command-line interfaces
├── modules/
│   └── nl2sql_father/ # NL2SQL parent graph (LangGraph)
├── configs/            # Configuration files
└── prompts/           # LLM prompts

tests/
├── unit/              # Unit tests
│   ├── metaweave/
│   └── vector_adapter/
└── integration/      # Integration tests
```

### Configuration Files

- YAML files for runtime configuration in `configs/`
- Environment variables in `.env` file (never commit secrets)
- Use `.env.example` as template for required variables

### Git Conventions

- Make meaningful commit messages
- Don't commit secrets, credentials, or `.env` files
- Run linting and tests before committing

## Common Development Tasks

### Running the NL2SQL CLI

```bash
# Single query
python scripts/nl2sql_subgraph_cli.py "查询2024年10月的销售额"

# Interactive mode
python scripts/nl2sql_subgraph_cli.py
```

### Running MetaWeave CLI

```bash
# See available commands
python -m src.metaweave.cli.main --help
```

## Dependencies

Key dependencies (see `pyproject.toml`):
- **LangGraph/LangChain**: Agent orchestration
- **FastAPI**: Web framework
- **psycopg/pgvector**: PostgreSQL and vector storage
- **neo4j**: Graph database
- **dashscope**: LLM API (Qwen)
- **pandas/numpy**: Data processing
- **pytest**: Testing framework
- **black/ruff**: Code formatting and linting
