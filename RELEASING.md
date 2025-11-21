# Releasing devtriage to PyPI

1. **Pre-flight**
   - Ensure `main` is clean and versioned (`devtriage.__version__` + `pyproject.toml` match).
   - Update `CHANGELOG.md` (if present) and verify tests pass: `pytest`.
2. **Build**
   ```
   python -m pip install --upgrade build twine
   python -m build
   ```
   This produces `dist/devtriage-<version>.tar.gz` and `.whl`.
3. **Publish**
   - Test upload (optional):
     `python -m twine upload --repository testpypi dist/*`
   - Real upload:
     `python -m twine upload dist/*`
4. **Tag & announce**
   - `git tag v<version> && git push origin v<version>`
   - Create a GitHub release in [DevMubarak1/Devtriage](https://github.com/DevMubarak1/Devtriage) with release notes.
5. **Post-release**
   - Confirm `pip install devtriage==<version>` succeeds in a clean environment.
   - Bump `__version__` to the next dev cycle if needed.

