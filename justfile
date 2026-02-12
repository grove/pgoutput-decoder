# Development workflow commands for pgoutput-decoder
# Install just: brew install just (macOS) or cargo install just

# List all available commands
default:
    @just --list

# Run all pre-commit checks (lint + format + test)
check: lint fmt-check test-rust clippy

# Lint Rust code
clippy:
    cargo clippy --all-targets --all-features -- -D warnings

# Format Rust code
fmt:
    cargo fmt

# Check Rust formatting without modifying files
fmt-check:
    cargo fmt -- --check

# Lint Python code
lint-python:
    uv run ruff check .

# Format Python code
fmt-python:
    uv run ruff format .

# Fix Python linting issues automatically
fix-python:
    uv run ruff check --fix .

# Run all linting (Rust + Python)
lint: clippy lint-python

# Run Rust tests
test-rust:
    cargo test

# Run Python tests
test-python:
    uv run pytest

# Run all tests
test: test-rust test-python

# Run tests with coverage report
coverage:
    uv run pytest --cov=pgoutput_decoder --cov-report=term --cov-report=html
    @echo ""
    @echo "📊 Coverage report generated in htmlcov/index.html"
    @echo "Run 'just coverage-view' to open in browser"

# Open coverage report in browser
coverage-view:
    open htmlcov/index.html

# Build Rust extension in development mode
dev:
    uv run maturin develop

# Build release wheels
build:
    uv run maturin build --release

# Clean build artifacts
clean:
    cargo clean
    rm -rf dist/ target/

# Setup development environment
setup:
    uv sync --all-extras
    uv run maturin develop

# Run before committing (full check)
pre-commit: fmt lint test
    @echo "✅ All checks passed! Safe to commit."

# Watch mode - auto-run clippy on file changes (requires cargo-watch)
watch:
    cargo watch -x "clippy --all-targets --all-features -- -D warnings"

# Watch mode for Python - auto-run ruff on file changes (requires watchexec)
watch-python:
    watchexec -e py -w python -w tests -w examples -- uv run ruff check .

# Install cargo-watch for watch mode
install-watch:
    cargo install cargo-watch

# Install watchexec for Python watch mode
install-watchexec:
    cargo install watchexec-cli
