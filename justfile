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

# Run Python tests (skips Docker tests by default)
test-python:
    uv run pytest tests/ -m "not docker" -v

# Run Python tests including Docker tests (requires Docker)
test-python-docker:
    uv run pytest tests/ -v

# Run all tests (Rust + Python, skips Docker tests)
test: test-rust test-python

# Run tests with coverage report
coverage:
    uv run pytest tests/ -m "not docker" --cov=pgoutput_decoder --cov-report=term --cov-report=html
    echo ""
    echo "📊 Coverage report generated in htmlcov/index.html"
    echo "Run 'just coverage-view' to open in browser"
    echo ""
    echo "💡 To include Docker tests, run 'just coverage-docker'"

# Run tests with coverage including Docker tests (requires Docker running)
coverage-docker:
    uv run pytest tests/ --cov=pgoutput_decoder --cov-report=term --cov-report=html
    echo ""
    echo "📊 Coverage report generated in htmlcov/index.html"

# Open coverage report in browser
coverage-view:
    open htmlcov/index.html

# Run tests with Rust code coverage (requires cargo-llvm-cov)
coverage-rust:
    #!/usr/bin/env bash
    set -euo pipefail
    export LLVM_COV=/opt/homebrew/opt/llvm/bin/llvm-cov
    export LLVM_PROFDATA=/opt/homebrew/opt/llvm/bin/llvm-profdata
    echo "🦀 Building with coverage instrumentation..."
    cargo llvm-cov clean --workspace
    RUSTFLAGS='-C instrument-coverage' uv sync
    RUSTFLAGS='-C instrument-coverage' LLVM_PROFILE_FILE='coverage-%p-%m.profraw' uv tool run maturin develop
    echo "🧪 Running Python tests to collect Rust coverage (skipping Docker tests)..."
    LLVM_PROFILE_FILE='coverage-%p-%m.profraw' uv run pytest tests/ -m "not docker" -v
    echo "📊 Generating Rust coverage report..."
    cargo llvm-cov report --lcov --output-path rust-coverage.lcov
    cargo llvm-cov report
    echo ""
    echo "✅ Rust coverage report saved to rust-coverage.lcov"
    echo ""
    echo "💡 To include Docker tests, run 'just coverage-rust-docker'"

# Run Rust coverage including Docker tests (requires Docker and cargo-llvm-cov)
coverage-rust-docker:
    #!/usr/bin/env bash
    export LLVM_COV=/opt/homebrew/opt/llvm/bin/llvm-cov
    export LLVM_PROFDATA=/opt/homebrew/opt/llvm/bin/llvm-profdata
    set -euo pipefail
    echo "🦀 Building with coverage instrumentation..."
    cargo llvm-cov clean --workspace
    RUSTFLAGS='-C instrument-coverage' uv sync
    RUSTFLAGS='-C instrument-coverage' LLVM_PROFILE_FILE='coverage-%p-%m.profraw' uv tool run maturin develop
    echo "🧪 Running ALL Python tests (including Docker) to collect Rust coverage..."
    LLVM_PROFILE_FILE='coverage-%p-%m.profraw' uv run pytest tests/ -v
    echo "📊 Generating Rust coverage report..."
    cargo llvm-cov report --lcov --output-path rust-coverage.lcov
    cargo llvm-cov report
    echo ""
    echo "✅ Rust coverage report saved to rust-coverage.lcov"

# Run combined Python + Rust coverage (skips Docker tests)
coverage-all:
    #!/usr/bin/env bash
    export LLVM_COV=/opt/homebrew/opt/llvm/bin/llvm-cov
    export LLVM_PROFDATA=/opt/homebrew/opt/llvm/bin/llvm-profdata
    set -euo pipefail
    echo "🐍 Python coverage:"
    uv run pytest tests/ -m "not docker" --cov=pgoutput_decoder --cov-report=term --cov-report=xml:python-coverage.xml
    echo ""
    echo "🦀 Rust coverage:"
    # Clean old profraw files
    rm -f *.profraw
    # Build with instrumentation
    RUSTFLAGS='-C instrument-coverage' uv tool run maturin develop
    # Run tests to generate profraw files
    LLVM_PROFILE_FILE='coverage-%p-%m.profraw' uv run pytest tests/ -m "not docker"
    # Merge profraw files
    $LLVM_PROFDATA merge -sparse *.profraw -o coverage.profdata
    # Generate report
    $LLVM_COV export --format=lcov \
        --instr-profile=coverage.profdata \
        --ignore-filename-regex='/.cargo/' \
        --ignore-filename-regex='/rustc/' \
        $(find target/debug -name "*.so" -o -name "*.dylib" | head -1) \
        > rust-coverage.lcov
    $LLVM_COV report \
        --instr-profile=coverage.profdata \
        --ignore-filename-regex='/.cargo/' \
        --ignore-filename-regex='/rustc/' \
        $(find target/debug -name "*.so" -o -name "*.dylib" | head -1)
    echo ""
    echo "✅ Coverage files generated:"
    echo "   - Python: python-coverage.xml"
    echo "   - Rust: rust-coverage.lcov"
    echo ""
    echo "💡 To include Docker tests, run 'just coverage-all-docker'"

# Run combined Python + Rust coverage including Docker tests
coverage-all-docker:
    #!/usr/bin/env bash
    export LLVM_COV=/opt/homebrew/opt/llvm/bin/llvm-cov
    export LLVM_PROFDATA=/opt/homebrew/opt/llvm/bin/llvm-profdata
    set -euo pipefail
    echo "⚠️  This requires Docker to be running!"
    echo ""
    echo "🐍 Python coverage:"
    uv run pytest tests/ --cov=pgoutput_decoder --cov-report=term --cov-report=xml:python-coverage.xml
    echo ""
    echo "🦀 Rust coverage:"
    cargo llvm-cov clean --workspace
    RUSTFLAGS='-C instrument-coverage' uv tool run maturin develop
    LLVM_PROFILE_FILE='coverage-%p-%m.profraw' uv run pytest tests/
    cargo llvm-cov report --lcov --output-path rust-coverage.lcov
    cargo llvm-cov report
    echo ""
    echo "✅ Coverage files generated:"
    echo "   - Python: python-coverage.xml"
    echo "   - Rust: rust-coverage.lcov"

# Install cargo-llvm-cov for Rust coverage
install-llvm-cov:
    rustup component add llvm-tools-preview
    cargo install cargo-llvm-cov

# Build Rust extension in development mode
dev:
    uv tool run maturin develop

# Build release wheels
build:
    uv tool run maturin build --release

# Clean build artifacts
clean:
    cargo clean
    rm -rf dist/ target/

# Setup development environment
setup:
    uv sync --all-extras
    uv tool run maturin develop

# Run before committing (full check)
pre-commit: fmt lint test
    echo "✅ All checks passed! Safe to commit."

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
