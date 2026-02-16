# Release Process

This document describes how to release new versions of `pgoutput-decoder` to GitHub and PyPI.

## Overview

Releases are fully automated via GitHub Actions. When you push a version tag, the CI/CD pipeline:

1. Builds wheels for all major platforms (Linux, macOS, Windows)
2. Creates a GitHub Release with all artifacts
3. Publishes to PyPI using Trusted Publishing (OIDC)

## Prerequisites

### One-Time PyPI Configuration

Configure **Trusted Publishing** (no API tokens needed):

1. **Production PyPI**: https://pypi.org/manage/account/publishing/
   - Add pending publisher:
     - PyPI Project Name: `pgoutput-decoder`
     - Owner: `geir.gronmo`
     - Repository: `pgoutput-decoder`
     - Workflow: `release.yml`
     - Environment: `pypi`

2. **Test PyPI** (optional): https://test.pypi.org/manage/account/publishing/
   - Same configuration with environment: `testpypi`

### Optional: GitHub Environment Protection

For additional safety, configure environments in GitHub Settings → Environments:

- **`pypi`**: Add required reviewers for production releases
- **`testpypi`**: No restrictions (for testing)

## Release Checklist

### 1. Pre-Release Validation

Run comprehensive checks locally:

```bash
# Format and lint checks
just check

# Run tests (requires Docker)
just test

# Generate coverage report
just coverage-all-docker

# Build and verify
just build
```

### 2. Update Version Numbers

Update version in **both** files (must match):

**`Cargo.toml`:**
```toml
[package]
version = "0.2.0"  # Update this
```

**`pyproject.toml`:**
```toml
[project]
version = "0.2.0"  # Update this
```

**Semantic Versioning Guidelines:**
- **Major** (`1.0.0`): Breaking API changes
- **Minor** (`0.2.0`): New features, backward-compatible
- **Patch** (`0.1.1`): Bug fixes, backward-compatible
- **Pre-release**: `0.2.0-alpha.1`, `0.2.0-beta.1`, `0.2.0-rc.1`

### 3. Commit Version Bump

```bash
git add Cargo.toml pyproject.toml
git commit -m "chore: bump version to 0.2.0"
```

### 4. Create Annotated Tag

Write detailed release notes in the tag message:

```bash
git tag -a v0.2.0 -m "Release v0.2.0

Features:
- Add synchronous wrapper examples
- Improve error handling
- Update documentation

Fixes:
- Fix LSN acknowledgement bug
- Resolve memory leak in replication stream

Breaking Changes:
- None
"
```

### 5. Push to Trigger Release

```bash
# Push commit and tag
git push origin main
git push origin v0.2.0

# Or push both at once
git push origin main --tags
```

### 6. Monitor Release Pipeline

Watch the progress at:
- **GitHub Actions**: https://github.com/geir.gronmo/pgoutput-decoder/actions
- **GitHub Releases**: https://github.com/geir.gronmo/pgoutput-decoder/releases

The pipeline builds for these platforms:
- **Linux**: x86_64, aarch64, armv7, s390x, ppc64le
- **macOS**: x86_64 (Intel), aarch64 (Apple Silicon)
- **Windows**: x64, x86, aarch64

### 7. Verify Published Package

After the pipeline completes:

```bash
# Install from PyPI
pip install pgoutput-decoder==0.2.0

# Verify version
python -c "import pgoutput_decoder; print(pgoutput_decoder.__version__)"

# Test basic functionality
python -c "
import pgoutput_decoder
reader = pgoutput_decoder.LogicalReplicationReader(
    publication_name='test',
    slot_name='test',
    host='localhost',
    database='test'
)
print('✅ Module works correctly')
"
```

### 8. Verify Release Artifacts

Check that the release includes:
- ✅ Source distribution (`.tar.gz`)
- ✅ Wheels for all platforms (`.whl`)
- ✅ Release notes from tag message
- ✅ Package published on PyPI

## Testing Pre-Release Versions

To test the release process without publishing to production:

### Option 1: Use Test PyPI

```bash
# Tag with pre-release version
git tag v0.2.0-beta.1

# Push to trigger build
git push origin v0.2.0-beta.1

# After pipeline completes, install from Test PyPI
pip install -i https://test.pypi.org/simple/ pgoutput-decoder==0.2.0b1

# Test the package
python -c "import pgoutput_decoder; print(pgoutput_decoder.__version__)"
```

### Option 2: Build Locally

```bash
# Build all wheels for your platform
just build

# Check artifacts
ls -lh target/wheels/

# Install locally
pip install target/wheels/pgoutput_decoder-*.whl --force-reinstall

# Test
python -c "import pgoutput_decoder; print('✅ Local build works')"
```

## Troubleshooting

### Version Already Exists on PyPI

**Problem**: PyPI doesn't allow overwriting published versions.

**Solution**: Bump to a new version and re-release:
```bash
# Delete the tag locally and remotely
git tag -d v0.2.0
git push origin :refs/tags/v0.2.0

# Update to v0.2.1 and try again
vim Cargo.toml pyproject.toml
git add Cargo.toml pyproject.toml
git commit -m "chore: bump version to 0.2.1"
git tag -a v0.2.1 -m "Release v0.2.1"
git push origin main --tags
```

### Trusted Publisher Not Configured

**Problem**: PyPI upload fails with authentication error.

**Solution**: Configure Trusted Publishing at https://pypi.org/manage/account/publishing/ as described in Prerequisites.

### Wheel Build Failed on Platform

**Problem**: GitHub Actions fails for specific platform (e.g., Windows ARM).

**Solution**:
1. Check GitHub Actions logs for the specific error
2. Common causes: missing dependencies, cross-compilation issues
3. Temporarily disable the failing platform in `.github/workflows/release.yml` if needed

### Version Mismatch Error

**Problem**: Maturin reports version mismatch between Cargo.toml and pyproject.toml.

**Solution**: Ensure both files have the exact same version string:
```bash
# Check versions match
grep '^version' Cargo.toml pyproject.toml

# Should show identical versions:
# Cargo.toml:version = "0.2.0"
# pyproject.toml:version = "0.2.0"
```

## Manual Release (Fallback)

If automated release fails, you can manually upload:

```bash
# Build distributions
uv tool run maturin build --release

# Verify builds
ls -lh target/wheels/

# Upload to PyPI (requires API token in ~/.pypirc)
uv tool install twine
uv tool run twine upload target/wheels/*
```

**Note**: Manual upload requires PyPI API tokens. Automated Trusted Publishing is preferred.

## Release Pipeline Details

The `.github/workflows/release.yml` workflow consists of:

1. **build** (matrix job): Builds wheels for all platforms
2. **sdist**: Builds source distribution
3. **testpypi**: Publishes to Test PyPI (optional validation)
4. **release**: Creates GitHub Release with artifacts
5. **pypi**: Publishes to production PyPI

All jobs use the official maturin GitHub Actions with OIDC authentication (no secrets required).

## Best Practices

1. **Test before tagging**: Always run `just check` and `just test` locally
2. **Use semantic versioning**: Follow semver strictly for version numbers
3. **Write detailed release notes**: Include features, fixes, and breaking changes in tag message
4. **Test pre-releases first**: Use `-alpha`, `-beta`, `-rc` versions for testing
5. **Monitor the pipeline**: Watch GitHub Actions to catch issues early
6. **Verify after publish**: Install from PyPI and test basic functionality
7. **Keep versions in sync**: Always update both Cargo.toml and pyproject.toml

## Quick Reference

```bash
# Complete release in 5 commands
just check && just build              # 1. Validate locally
vim Cargo.toml pyproject.toml         # 2. Update versions
git add -A && git commit -m "chore: bump version to X.Y.Z"  # 3. Commit
git tag -a vX.Y.Z -m "Release notes"  # 4. Create tag
git push origin main --tags           # 5. Trigger release

# Monitor and verify
open https://github.com/geir.gronmo/pgoutput-decoder/actions
pip install pgoutput-decoder==X.Y.Z
python -c "import pgoutput_decoder; print(pgoutput_decoder.__version__)"
```

## Post-Release

After a successful release:

1. ✅ Verify package appears on PyPI
2. ✅ Update documentation if needed
3. ✅ Announce release (GitHub Discussions, social media, etc.)
4. ✅ Monitor for issues from users
5. ✅ Update project board/milestones for next release

## Resources

- **GitHub Releases**: https://github.com/geir.gronmo/pgoutput-decoder/releases
- **PyPI Package**: https://pypi.org/project/pgoutput-decoder/
- **PyPI Stats**: https://pypistats.org/packages/pgoutput-decoder
- **GitHub Actions**: https://github.com/geir.gronmo/pgoutput-decoder/actions
- **Maturin Docs**: https://www.maturin.rs/
- **PyPI Trusted Publishing**: https://docs.pypi.org/trusted-publishers/
