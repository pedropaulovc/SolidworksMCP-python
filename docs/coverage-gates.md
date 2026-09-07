# Coverage gates

The CI coverage policy has two checks:

- Every authored module under `src/solidworks_mcp` remains in the 90% execution-coverage gate, including `sw_type_info.py` and all drawing, recovery and launcher code.
- Exactly `adapters/_generated/sldworks_2026.py`, the checked-in pywin32 makepy output, has a separate integrity/version/API-contract gate. No `_generated/` wildcard or runtime-package exclusion is used.

The generated gate checks the complete SHA-256 after Git's CRLF/LF conversion,
Python syntax, typelib identity/version and independent typed-dispatch fixtures
for critical methods. It does not claim native execution or geometric correctness.
Regenerating the binding requires reviewing the new artifact and updating these
contracts deliberately. Native SolidWorks acceptance remains separate.

## Why the scope changed

The baseline at `2269009` already failed CI: [run 32779676003](https://github.com/pedropaulovc/SolidworksMCP-python/actions/runs/32779676003)
passed 1,937 tests and skipped 50, but reported 29.29% coverage. The generated
binding accounted for 34,306 unexecuted statements on Linux.

[PR 101 run 34059459918](https://github.com/pedropaulovc/SolidworksMCP-python/actions/runs/34059459918)
passed 1,970 tests and skipped 51: 29.41% overall. The generated file was unchanged.
Authored code alone covered 15,180 of 17,301 statements (87.74%), still below 90%.
The separate artifact gate therefore does not itself make CI pass: behavioral
tests must close the remaining authored-code gap. The threshold stays at 90%.

The added drawing tests check document and view ownership, native argument
selection, dimension curation, callout grouping, and fresh-file export handling.
Recovery tests check registry fields, process targeting, deadlines and CLI error
propagation. Their native/OS boundaries are test doubles: they establish Python
behavior, not successful CAD creation or a licensed SolidWorks launch.

Run the static contract with:

```text
uv run --extra dev --extra test python -m pytest tests/solidworks_mcp/adapters/test_generated_binding_contract.py --no-cov
```

Run full mock execution coverage with the normal `make test` CI command; do not
use the static check as a substitute for it.
